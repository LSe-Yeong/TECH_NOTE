# 읽기가 쓰기를 막지 않는 원리 — MVCC는 그 대가를 어디에 쌓는가

기준 버전: **MySQL 8.4 LTS (InnoDB)**, **PostgreSQL 18**

## 1. 핵심 개념 — 락을 없앤 게 아니라 버전을 늘린 것입니다

다중 버전 동시성 제어(MVCC, Multi-Version Concurrency Control)는 **같은 행을 여러 시점의 버전으로 동시에 보관하는 방식**입니다. 읽는 쪽은 자기 시점에 맞는 과거 버전을 받아가고, 쓰는 쪽은 그와 무관하게 새 버전을 만듭니다. PostgreSQL 문서는 이 성질을 이렇게 못 박습니다 — "읽기가 쓰기를 막지 않고, 쓰기가 읽기를 막지 않습니다" ([PostgreSQL 18, MVCC 소개](https://www.postgresql.org/docs/current/mvcc-intro.html)).

> MVCC가 없으면 어떻게 되는지는 읽기 락만 떠올리면 됩니다. 월말 정산 쿼리가 주문 테이블을 30초 훑는 동안, 그 범위에 들어온 주문은 전부 `INSERT`가 멈춥니다. 반대로 결제가 한 건 진행 중이면 대시보드 조회가 멈춥니다. 조회 한 번과 쓰기 한 번이 서로를 기다리는 구조에서는 트래픽이 조금만 늘어도 커넥션 풀이 먼저 말라붙습니다.

여기서 반드시 같이 가야 하는 질문이 있는데, 대부분 이걸 빼고 MVCC를 이해합니다.

**과거 버전은 누가 만들고, 어디에 쌓이고, 누가 치웁니까.**

MVCC는 충돌을 없앤 게 아니라 **기다림을 저장 공간으로 환전한 것**입니다. 환전한 돈은 어딘가에 쌓이고, 누군가 치워야 합니다. MySQL과 PostgreSQL의 운영 차이 대부분이 "어디에 쌓는가" 한 가지 선택에서 갈라집니다.

---

## 2. 구조 — 행 하나가 여러 시점을 갖는 방법

### 2-1. InnoDB — 현재 버전은 제자리에, 과거는 undo로

InnoDB는 모든 행에 숨은 컬럼 3개를 붙입니다.

| 컬럼 | 크기 | 역할 |
|---|---:|---|
| `DB_TRX_ID` | 6바이트 | 이 행을 마지막으로 삽입·수정한 트랜잭션 ID |
| `DB_ROLL_PTR` | 7바이트 | 롤백 세그먼트의 undo 로그 레코드를 가리키는 롤 포인터 |
| `DB_ROW_ID` | 6바이트 | 클러스터 인덱스를 자동 생성한 경우에만 쓰이는 행 ID |

출처: [InnoDB Multi-Versioning](https://dev.mysql.com/doc/refman/8.4/en/innodb-multi-versioning.html)

클러스터 인덱스의 레코드는 **제자리에서 갱신**됩니다. 그래서 테이블에는 항상 최신 버전만 있습니다. 과거 버전은 테이블이 아니라 undo 로그에 있고, 읽는 트랜잭션은 롤 포인터를 따라가며 버전을 되감습니다.

```
현재 행 (최신) → undo 레코드 → undo 레코드 → ... (과거로)
   DB_TRX_ID 비교 → 내 스냅샷보다 나중 것이면 한 칸 더 되감기
```

`DELETE`도 물리 삭제가 아닙니다. 삭제 표시 비트를 세우는 **업데이트로 내부 처리**되고, 실제 제거는 purge라는 백그라운드 작업이 undo 레코드를 버릴 때 일어납니다.

undo 로그는 두 종류로 수명이 다릅니다. 이 구분이 뒤에 나올 함정의 뿌리입니다.

- **insert undo** — 롤백에만 필요하므로 **커밋 즉시 버립니다**
- **update undo** — 일관된 읽기의 재료이므로, **그 정보를 필요로 할 수 있는 스냅샷이 하나도 남지 않을 때까지 버리지 못합니다**

### 2-2. PostgreSQL — 과거도 현재도 같은 테이블에

PostgreSQL은 undo 영역이 따로 없습니다. `UPDATE`는 기존 튜플을 고치지 않고 **새 튜플을 테이블(힙)에 추가**합니다. 각 튜플은 시스템 컬럼으로 자기 생존 구간을 들고 있습니다.

- `xmin` — 이 버전을 삽입한 트랜잭션 ID
- `xmax` — 이 버전을 삭제·갱신한 트랜잭션 ID. 살아있는 버전은 0입니다 ([시스템 컬럼](https://www.postgresql.org/docs/current/ddl-system-columns.html))

읽는 트랜잭션은 자기 스냅샷과 `xmin`/`xmax`를 비교해 "그 시점에 살아있던 버전"을 고릅니다. 지나간 버전은 **죽은 튜플(dead tuple)** 로 테이블 안에 그대로 남고, `VACUUM`이 와서 공간을 재사용 가능하게 만듭니다.

### 2-3. 그래서 갈라지는 것들

같은 MVCC인데 운영 체감이 다른 이유가 여기서 전부 설명됩니다.

| | InnoDB | PostgreSQL |
|---|---|---|
| 과거 버전 위치 | undo 로그 (테이블 외부) | 테이블 내부 (죽은 튜플) |
| `UPDATE` 시 인덱스 | 변경된 컬럼의 인덱스만 손댐 | 새 튜플이므로 원칙적으로 모든 인덱스에 항목 추가 |
| 뒷정리 주체 | purge 스레드 | `VACUUM` / autovacuum |
| 긴 트랜잭션의 피해 형태 | undo 누적 → 버전 체인 길어져 **읽기가 느려짐** | 죽은 튜플 누적 → **테이블이 부풀고 스캔량이 늘어남** |
| 공간 회수 | undo 테이블스페이스 truncate | 기본 `VACUUM`은 OS에 반환하지 않음 |

InnoDB의 `UPDATE`가 테이블을 부풀리지 않는 대신, 과거를 보는 쿼리가 체인을 되감느라 느려집니다. PostgreSQL은 과거를 보는 쿼리가 빠른 대신, 테이블 자체가 커집니다. **둘 중 어느 쪽도 공짜가 아니고, 비용이 나타나는 지표가 다릅니다.**

보조 인덱스에서 InnoDB는 한 번 더 갈라집니다. 보조 인덱스 레코드에는 숨은 시스템 컬럼이 없고 제자리 갱신도 되지 않습니다. 인덱스 컬럼이 바뀌면 **기존 레코드를 삭제 표시하고 새 레코드를 넣습니다.** 그리고 조회할 때 삭제 표시된 레코드를 만나거나 더 최신 트랜잭션이 그 페이지를 건드렸으면, 클러스터 인덱스까지 찾아가 `DB_TRX_ID`를 확인하고 undo에서 버전을 복원합니다. 이때 **커버링 인덱스 기법은 사용되지 않습니다**(위 출처). 인덱스만 보고 끝낼 수 있던 쿼리가 갱신 직후에만 느려지는 현상의 정체입니다 — 실행계획은 그대로인데 시간이 변합니다.

---

## 3. 어떤 버전을 보여줄지 정하는 시점 — 스냅샷

버전이 여러 개 있다는 것만으로는 부족합니다. **"내 시점"을 언제 확정하는지**가 격리 수준의 실체입니다.

| | MySQL InnoDB | PostgreSQL |
|---|---|---|
| READ COMMITTED | 일관된 읽기마다 새 스냅샷 | 각 명령문 시작 시점의 스냅샷 |
| REPEATABLE READ | **트랜잭션의 첫 일관된 읽기**가 만든 스냅샷을 끝까지 사용 | **첫 트랜잭션 제어문이 아닌 문장** 시점의 스냅샷 |

출처: [Consistent Nonlocking Reads](https://dev.mysql.com/doc/refman/8.4/en/innodb-consistent-read.html), [Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html)

주목할 지점은 양쪽 다 **`BEGIN` 시점이 아니라는 것**입니다. `BEGIN` 직후 10초 쉬었다가 첫 `SELECT`를 던지면 스냅샷은 그 `SELECT` 시점에 찍힙니다. "트랜잭션을 먼저 열어뒀으니 그 시점 데이터가 보일 것"이라는 가정으로 짠 로직은 어긋납니다.

### 3-1. MVCC로 읽지 않는 읽기가 있습니다

여기가 가장 많이 사고가 나는 곳입니다. 스냅샷은 **일반 `SELECT`에 적용되고, DML에는 반드시 적용되지 않습니다.** MySQL 문서의 예시가 직설적입니다.

다른 세션이 `status = 'PENDING'`인 주문 10건을 방금 커밋한 상황을 가정합니다.

```sql
-- REPEATABLE READ 트랜잭션 안에서
START TRANSACTION;

SELECT COUNT(*) FROM orders WHERE status = 'PENDING';
-- 0건. 내 스냅샷에는 그 10건이 없습니다

UPDATE orders SET status = 'CANCELED' WHERE status = 'PENDING';
-- Rows matched: 10  Changed: 10   (!)

SELECT COUNT(*) FROM orders WHERE status = 'CANCELED';
-- 10건. 이제 보입니다

COMMIT;
```

보이지도 않던 주문 10건이 취소됩니다. `UPDATE`·`DELETE`·`SELECT ... FOR UPDATE`는 과거 버전이 아니라 **현재 커밋된 최신 버전**을 보고 락을 겁니다. 그래야 이미 사라진 행을 수정하는 일이 없기 때문입니다.

PostgreSQL도 같은 문제를 다르게 처리합니다. READ COMMITTED에서는 선행 트랜잭션을 기다린 뒤 **최신 버전에 대해 `WHERE` 절을 다시 평가**해서, 여전히 조건에 맞으면 진행합니다. REPEATABLE READ에서는 그냥 실패시킵니다.

```
ERROR: could not serialize access due to concurrent update
```

이 에러는 버그가 아니라 설계된 결과이므로, **애플리케이션이 트랜잭션 전체를 재시도해야 합니다.**

조회로 확인하고 그 결과로 수정하는 코드가 MVCC에서 깨지는 이유가 이것입니다. 확인은 과거를 보고, 수정은 현재에 적용됩니다. 구체적인 이상현상 이름과 대처는 `daily/day71-isolation-anomaly.md`에서 다뤘습니다.

### 3-2. 스냅샷을 앞으로 당기는 방법

REPEATABLE READ에서 최신을 봐야 하면 선택지는 셋뿐입니다. 커밋하고 다시 읽거나, `START TRANSACTION WITH CONSISTENT SNAPSHOT`으로 새로 시작하거나, `FOR SHARE`·`FOR UPDATE`로 잠금 읽기를 하는 것입니다. 잠금 읽기는 최신을 보장받는 대신 **대기가 돌아옵니다** — MVCC의 이점을 그 쿼리에서 반납하는 셈입니다.

덧붙여 `INSERT ... SELECT`나 `CREATE TABLE ... SELECT`는 기본적으로 더 강한 락을 쓰고, **`SELECT` 부분이 READ COMMITTED처럼 동작**합니다. 같은 트랜잭션 안인데 앞의 `SELECT`와 다른 결과를 볼 수 있습니다.

---

## 4. 대가는 뒷정리에 쌓입니다

### 4-1. InnoDB — purge와 History list length

InnoDB는 삭제 표시된 인덱스 레코드를 가진 트랜잭션 목록을 들고 있고, 그 길이가 purge 지연입니다.

```sql
SHOW ENGINE INNODB STATUS\G
-- TRANSACTIONS 섹션
-- History list length 20
```

문서는 이 값이 "**보통 수천 미만의 낮은 값**"이라고 말합니다. 쓰기가 많거나 긴 트랜잭션이 있으면 올라가는데, **읽기 전용 트랜잭션도 올립니다.** 문서가 직접 드는 두 예가 실무에서 그대로 재현됩니다.

1. 동시 DML이 많은 상황에서 `mysqldump --single-transaction` 실행
2. `autocommit`을 끈 채 `SELECT`를 돌리고 `COMMIT`/`ROLLBACK`을 잊음

출처: [Purge Configuration](https://dev.mysql.com/doc/refman/8.4/en/innodb-purge-configuration.html)

관련 기본값도 같은 문서에 있습니다. `innodb_max_purge_lag`는 **0(제한 없음)** 이라 기본 상태에서는 purge가 아무리 밀려도 쓰기를 늦추지 않습니다. `innodb_purge_threads`는 논리 프로세서가 16개 이하면 1, 아니면 4입니다.

undo 테이블스페이스는 초기화 때 `undo_001`, `undo_002` 두 개가 만들어집니다. `innodb_max_undo_log_size`(기본 1073741824바이트 = 1024MiB)를 넘으면 truncate 대상이 되고, 비워진 뒤 **16MB로 잘립니다**. 검사 주기는 purge 호출 128회마다입니다(`innodb_purge_rseg_truncate_frequency`) — 출처: [Undo Tablespaces](https://dev.mysql.com/doc/refman/8.4/en/innodb-undo-tablespaces.html).

<!-- TODO: 확인 필요 — innodb_undo_log_truncate의 기본값이 ON이라는 근거는 MySQL 8.0.2 블로그와 WL#10499(기본값 OFF→ON 변경)이고, 8.4 레퍼런스 매뉴얼 본문에서는 기본값이 명시된 문장을 찾지 못했습니다. 실제 인스턴스에서 SELECT @@innodb_undo_log_truncate; 로 확인하는 편이 안전합니다. -->

### 4-2. PostgreSQL — VACUUM과 부풀기

PostgreSQL은 죽은 튜플이 테이블에 남으므로, `VACUUM`을 못 돌리면 테이블이 커집니다. 중요한 건 **기본 `VACUUM`은 공간을 OS에 반환하지 않는다**는 점입니다. 재사용 가능하게 표시할 뿐입니다. 실제로 파일을 줄이는 `VACUUM FULL`은 `ACCESS EXCLUSIVE` 락을 잡아 **그 테이블을 아무도 못 쓰게 만들고**, 새 사본을 쓰는 동안 추가 디스크 공간까지 요구합니다. "용량이 안 줄어서 `VACUUM FULL` 돌렸다가 서비스가 멈췄다"는 사고가 여기서 나옵니다. 출처: [Routine Vacuuming](https://www.postgresql.org/docs/current/routine-vacuuming.html)

여기에 PostgreSQL만의 시한폭탄이 하나 더 있습니다. 트랜잭션 ID는 유한해서 주기적으로 동결해야 합니다. `autovacuum_freeze_max_age`는 기본 2억이고, 오래된 XID가 순환 지점까지 4천만 트랜잭션 남으면 경고가 뜨고, **3백만 미만이 되면 새 XID 할당을 거부합니다.** 쓰기가 전부 멈춥니다.

### 4-3. 공통 원인은 하나입니다

양쪽의 지표는 다르지만 1순위 원인은 같습니다. **끝나지 않은 트랜잭션입니다.**

- InnoDB: 스냅샷이 살아있으면 update undo를 버릴 수 없습니다
- PostgreSQL: 열린 트랜잭션은 그 트랜잭션에만 보일 수 있는 최근 죽은 튜플의 정리를 막습니다. 문서가 이를 테이블 부풀기의 원인으로 직접 지목합니다 ([`idle_in_transaction_session_timeout`](https://www.postgresql.org/docs/current/runtime-config-client.html))

PostgreSQL에서는 복제 슬롯과 미해결 prepared 트랜잭션도 같은 지평선을 붙잡습니다. 특히 **없어진 복제본의 슬롯이 남아 있는 경우**는 애플리케이션 코드를 아무리 봐도 원인이 안 보입니다.

---

## 5. 예제 — 읽기 전용 작업이 쓰기를 느리게 만드는 코드

### 5-1. 클린하지 않은 코드 ❌

```java
@Service
@RequiredArgsConstructor
public class SettlementReportService {

    private final OrderRepository orderRepository;
    private final ReportWriter reportWriter;

    // ❌ 50만 건을 한 트랜잭션 안에서 처리합니다.
    //    읽기 전용이라 "DB에 부담이 없다"고 생각하기 쉽습니다.
    @Transactional(readOnly = true)
    public void generateMonthlyReport(YearMonth month) {
        List<Order> orders = orderRepository.findAllByOrderMonth(month);
        for (Order order : orders) {
            reportWriter.append(toReportRow(order));   // 외부 파일 쓰기, 건당 수 ms
        }
        reportWriter.flush();
    }
}
```

문제는 쿼리가 아니라 **트랜잭션이 열려 있는 시간**입니다. 이 메서드가 20분 걸리면 스냅샷이 20분간 살아있습니다. 그동안 주문 테이블에 들어온 모든 변경의 과거 버전을 DB가 버리지 못합니다. InnoDB면 History list length가 올라가고 undo가 자라며, PostgreSQL이면 autovacuum이 돌아도 죽은 튜플을 못 치워 테이블이 부풉니다.

증상은 엉뚱한 곳에서 나타납니다. **정산 배치가 도는 시간대에만 주문 조회 API의 p99가 올라갑니다.** 정산 쿼리는 느리지 않고, 슬로우 쿼리 로그에는 정산이 안 찍힐 수도 있습니다.

### 5-2. 개선한 코드 ✔️

```java
@Service
@RequiredArgsConstructor
public class SettlementReportService {

    private final SettlementReportService self;   // 프록시 경유용
    private final OrderRepository orderRepository;
    private final ReportWriter reportWriter;

    private static final int CHUNK_SIZE = 1_000;

    // ✔️ 트랜잭션 밖에서 루프를 돌립니다. 느린 작업은 전부 여기에 둡니다.
    public void generateMonthlyReport(YearMonth month) {
        long lastId = 0L;
        while (true) {
            List<Order> chunk = self.fetchChunk(month, lastId, CHUNK_SIZE);
            if (chunk.isEmpty()) {
                break;
            }
            for (Order order : chunk) {
                reportWriter.append(toReportRow(order));   // 트랜잭션 밖
            }
            lastId = chunk.get(chunk.size() - 1).getId();
        }
        reportWriter.flush();
    }

    // ✔️ 스냅샷의 수명이 이 메서드 한 번으로 끝납니다.
    @Transactional(readOnly = true)
    public List<Order> fetchChunk(YearMonth month, long lastId, int size) {
        return orderRepository.findChunkAfterId(month, lastId, size);
    }
}
```

바뀐 건 하나입니다. **긴 작업과 긴 스냅샷을 분리했습니다.** 트랜잭션은 청크 하나를 읽는 동안만 열립니다.

여기서 `OFFSET`이 아니라 마지막 ID 기준으로 끊은 것도 의도적입니다. 청크마다 스냅샷이 새로 찍히므로 중간에 데이터가 바뀌면 `OFFSET` 페이징은 행을 건너뛰거나 중복시킵니다. 그리고 `readOnly = true`가 실제로 무엇을 하고 무엇을 하지 않는지는 `daily/day62-readonly-true.md`에 있습니다 — **쓰기를 막아주지 않습니다.**

> 주의: `self` 자기 주입은 프록시를 경유하기 위한 것입니다. 같은 클래스 내부 호출로는 `@Transactional`이 걸리지 않습니다.

---

## 6. 진단 — 지금 누가 과거를 붙잡고 있는가

```sql
-- MySQL: 오래 열려 있는 트랜잭션 찾기
SELECT trx_id, trx_started,
       TIMESTAMPDIFF(SECOND, trx_started, NOW()) AS age_sec,
       trx_rows_modified, trx_state
FROM information_schema.innodb_trx
ORDER BY trx_started;
```

`trx_state`가 `RUNNING`인데 `age_sec`이 수백 초이고 `trx_rows_modified`가 0이면, 바로 그 **아무것도 안 쓰는 트랜잭션**이 undo를 붙잡고 있는 범인입니다.

```sql
-- PostgreSQL: 정리 지평선을 붙잡은 세션 찾기
SELECT pid, state, xact_start, backend_xid, backend_xmin,
       age(backend_xmin) AS xmin_age, left(query, 60) AS query
FROM pg_stat_activity
WHERE backend_xmin IS NOT NULL
ORDER BY xmin_age DESC;
```

여기서 안 나오면 `pg_replication_slots`의 `age(xmin)`과 `pg_prepared_xacts`의 `age(transactionid)`를 봅니다. 문서가 순환 대응 절차로 제시하는 점검 대상이 그대로 부풀기 점검 대상입니다.

---

## 7. 함정

### 7-1. `autocommit`을 끈 클라이언트의 조회 하나

- **증상**: 쓰기를 안 했는데 History list length가 수십만으로 자라고, 디스크 사용량이 계속 늘어납니다. undo 테이블스페이스가 커집니다.
- **원인**: `autocommit=0` 상태에서 `SELECT`를 던지면 트랜잭션이 시작되고, `COMMIT`을 안 하면 스냅샷이 계속 살아 update undo를 버릴 수 없습니다. BI 도구나 DB 클라이언트 탭을 켜두면 재현됩니다.
- **해법**: 조회 세션에도 커밋을 넣습니다. 세션 단위로 `autocommit=1`을 쓰거나, 서버 쪽에서 `innodb_trx`를 주기 점검해 장시간 유휴 트랜잭션을 끊습니다.

### 7-2. 백업이 서비스를 느리게 만듭니다

- **증상**: 야간 백업 시간대에 쓰기 지연이 올라가고, 끝난 뒤에도 한동안 회복되지 않습니다.
- **원인**: `mysqldump --single-transaction`은 일관성을 위해 스냅샷을 백업이 끝날 때까지 유지합니다. 그 사이의 DML 과거 버전이 전부 누적됩니다. 문서가 History list length 증가의 대표 예로 드는 시나리오입니다.
- **해법**: 백업을 복제본에서 받습니다. 복제본에서 받더라도 그 복제본의 undo는 자라므로, 백업 소요 시간 자체를 줄이거나 물리 백업으로 바꿉니다.

### 7-3. `DELETE`로 절반을 지웠는데 용량이 안 줄어듭니다

- **증상**: 수천만 건을 지웠는데 디스크 사용량이 그대로이거나 오히려 늘어납니다.
- **원인**: 양쪽 다 즉시 물리 삭제가 아닙니다. InnoDB는 삭제 표시만 하고 purge를 기다리며, purge가 끝나도 비워진 페이지는 테이블 파일 안에 남습니다. PostgreSQL은 기본 `VACUUM`이 공간을 OS에 반환하지 않습니다. 게다가 `DELETE` 자체가 undo·죽은 튜플을 대량 생성하므로 진행 중에는 늘어납니다.
- **해법**: 공간 회수가 목적이면 테이블 재구성이 필요합니다. 다만 두 DB의 부담이 다릅니다. InnoDB의 `OPTIMIZE TABLE`은 `ALTER TABLE ... FORCE`로 매핑되고 일반·파티션 테이블에서는 온라인 DDL로 수행되어, **배타 락은 준비 단계와 커밋 단계에만 짧게** 걸립니다(단, `FULLTEXT` 인덱스가 있으면 테이블 복사 방식으로 떨어집니다 — [OPTIMIZE TABLE](https://dev.mysql.com/doc/refman/8.4/en/optimize-table.html)). 반면 PostgreSQL `VACUUM FULL`은 작업 내내 `ACCESS EXCLUSIVE` 락을 잡습니다. 무중단이 필요하면 `pg_repack` 같은 외부 도구를 검토하고, 반복 삭제가 예정된 데이터라면 애초에 파티션으로 설계해 파티션 단위로 버리는 쪽이 낫습니다.

### 7-4. 긴 읽기를 복제본으로 보냈는데도 원본이 영향을 받습니다

- **증상**: 리포팅 쿼리를 읽기 복제본으로 옮겼는데 원본 테이블의 부풀기가 멈추지 않습니다. 또는 복제본의 긴 쿼리가 원인 없이 취소됩니다.
- **원인**: PostgreSQL에는 이게 **설정으로 명시된 트레이드오프**로 존재합니다. `hot_standby_feedback`을 켜면 복제본이 실행 중인 쿼리 정보를 원본에 보내고, 원본의 `VACUUM`은 그 쿼리에 필요한 최근 죽은 행을 지우지 않습니다. 복제본 쿼리가 취소되는 문제는 사라지지만 **원본이 부풉니다.** 기본값은 `off`입니다 ([복제 설정](https://www.postgresql.org/docs/current/runtime-config-replication.html)). 끄면 반대로 복제본의 긴 쿼리가 정리 충돌로 취소됩니다. 그리고 복제 슬롯의 `xmin`도 같은 지평선을 붙잡으므로, **끊긴 복제본의 슬롯이 남아 있으면 쿼리가 하나도 없어도 계속 막힙니다.**
- **해법**: 둘 중 무엇을 포기할지 정하는 문제입니다. 복제본 쿼리를 살려야 하면 `hot_standby_feedback`을 켜고 원본 부풀기를 감시 항목에 넣고, 원본을 지켜야 하면 끈 상태로 `max_standby_streaming_delay`를 조정해 취소를 감수합니다. 어느 쪽이든 `pg_replication_slots`의 `age(xmin)`을 감시하고 쓰지 않는 슬롯은 제거합니다. 살아있는 복제본의 슬롯을 지우면 그 복제본을 재구축해야 하므로 반드시 확인 후 삭제합니다.

### 7-5. 유휴 트랜잭션을 끊어주는 안전장치가 기본적으로 꺼져 있습니다

- **증상**: 애플리케이션이 커넥션을 반납하지 않거나 예외로 빠져나간 경로 때문에 트랜잭션이 영원히 열려 있습니다. 아무도 모릅니다.
- **원인**: PostgreSQL의 `idle_in_transaction_session_timeout`, `transaction_timeout`, `idle_session_timeout`은 **모두 기본값이 0(비활성)** 입니다. 서버가 알아서 끊어주지 않습니다.
- **해법**: 운영 DB에서 `idle_in_transaction_session_timeout`을 설정합니다. 다만 커넥션 풀 뒤에서 세션이 갑자기 끊기면 풀이 반응을 못 하는 경우가 있으므로, 전역보다 역할·사용자 단위 적용부터 검토합니다.

<!-- TODO: 확인 필요 — transaction_timeout은 PostgreSQL 18 문서에 존재하지만, 어느 버전에서 도입됐는지는 확인하지 않았습니다. 하위 버전 환경에서는 존재 여부를 먼저 확인해야 합니다. -->

### 7-6. 트랜잭션 중에 스키마가 바뀌면 읽기가 실패합니다

- **증상**: 긴 트랜잭션 도중 `ER_TABLE_DEF_CHANGED` — "Table definition has changed, please retry transaction"이 발생합니다.
- **원인**: 테이블을 복사하는 방식의 `ALTER TABLE`이 끼어들면, 새 테이블의 행은 내 스냅샷 시점에 존재하지 않았으므로 일관된 읽기를 이어갈 수 없습니다. `DROP TABLE`에 대해서도 일관된 읽기는 동작하지 않습니다.
- **해법**: 에러 이름 그대로 재시도가 정답입니다. 그리고 배포 중 스키마 변경과 장시간 배치가 겹치지 않게 일정을 분리합니다.

---

## 8. 관련 개념과 비교

| 개념 | MVCC와의 관계 |
|---|---|
| 락 | MVCC는 **읽기-쓰기** 충돌만 없앱니다. 쓰기-쓰기 충돌은 그대로 락으로 해결합니다 |
| 격리 수준 | "스냅샷을 언제 찍는가"를 고르는 다이얼입니다 (`daily/day71-isolation-anomaly.md`) |
| ACID의 I | 격리를 구현하는 수단 중 하나입니다. undo 로그는 A(원자성)와 재료를 공유합니다 (`daily/day65-acid.md`) |
| 낙관적 락 | MVCC가 일관된 읽기를 제공해도 검사-갱신 경합은 남으므로, 버전 컬럼으로 애플리케이션이 따로 막습니다 |

핵심을 한 줄로 줄이면 이렇습니다. **MVCC는 동시성 문제를 없애지 않고, 대기를 공간과 뒷정리 작업으로 바꿉니다.** 그 비용은 트랜잭션을 짧게 유지하는 쪽이 지불하지 않고, **길게 여는 쪽이 모두에게 전가합니다.**

---

## 9. 참고자료

- [MySQL 8.4 — InnoDB Multi-Versioning](https://dev.mysql.com/doc/refman/8.4/en/innodb-multi-versioning.html)
- [MySQL 8.4 — Consistent Nonlocking Reads](https://dev.mysql.com/doc/refman/8.4/en/innodb-consistent-read.html)
- [MySQL 8.4 — Purge Configuration](https://dev.mysql.com/doc/refman/8.4/en/innodb-purge-configuration.html)
- [MySQL 8.4 — Undo Tablespaces](https://dev.mysql.com/doc/refman/8.4/en/innodb-undo-tablespaces.html)
- [MySQL 8.4 — Undo Logs](https://dev.mysql.com/doc/refman/8.4/en/innodb-undo-logs.html)
- [PostgreSQL 18 — Introduction to MVCC](https://www.postgresql.org/docs/current/mvcc-intro.html)
- [PostgreSQL 18 — Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
- [PostgreSQL 18 — Routine Vacuuming](https://www.postgresql.org/docs/current/routine-vacuuming.html)
- [PostgreSQL 18 — System Columns](https://www.postgresql.org/docs/current/ddl-system-columns.html)
- [PostgreSQL 18 — Client Connection Defaults](https://www.postgresql.org/docs/current/runtime-config-client.html)
