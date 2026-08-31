# 인덱스는 어떻게 빠른가 — B+Tree의 내부

> 이 문서가 답할 질문: **"정렬해두면 빠르다" 다음이 궁금할 때, B+Tree는 실제로 어떤 구조이고 왜 이진 탐색 트리도 해시도 아닌 이것이 표준이 되었는가?**
>
> 기준: MySQL 8.4 / InnoDB, 일부 대조에 PostgreSQL 17 (2026년 8월 확인). `day17-why-index.md`가 "인덱스가 없애는 비용"을 다뤘다면 이 문서는 그 구조 안으로 들어갑니다. 클러스터형/세컨더리 인덱스와 페이지 단위 비용은 이미 안다고 가정합니다.

## 1. 핵심 개념 — 디스크에서는 비교 횟수가 비용이 아닙니다

알고리즘 수업에서 배운 탐색 비용은 **비교 횟수**입니다. 이진 탐색 트리가 O(log n)이라고 할 때 그 log는 키를 몇 번 비교하는지를 셉니다. 메모리 안에서는 이게 맞는 모델입니다.

데이터베이스에서는 틀립니다. 키 비교는 CPU 연산이라 사실상 공짜고, 진짜 비용은 **페이지를 가져오는 횟수**입니다. 이 기준을 바꿔 끼우면 자료구조 순위가 뒤집힙니다.

100만 행 테이블을 가정합니다.

| 구조 | 노드 하나에 담기는 키 | 깊이 | 방문할 페이지 |
|---|---:|---:|---:|
| 이진 탐색 트리 | 1개 | 약 20 | 약 20장 |
| B+Tree (16KB 페이지) | 수백 개 | 3~4 | 3~4장 |

> 이진 탐색 트리는 비교를 20번 하고, B+Tree도 비교는 비슷하게 합니다. 차이는 **그 비교를 몇 장의 페이지에 흩어놓느냐**입니다. 이 관점이 없으면 "정렬돼 있으니까 빠르다"에서 멈추고, 왜 키 길이가 성능을 바꾸는지·왜 대량 삭제 후에도 인덱스가 안 줄어드는지·왜 인덱스를 다시 만들면 잠깐 빨라지는지를 설명하지 못합니다. 아래 내용은 전부 "페이지 한 장에 뭘 얼마나 담느냐"의 결과입니다.

InnoDB의 인덱스는 공간 인덱스를 제외하면 전부 B-tree 계열 구조입니다. 공간 인덱스만 R-tree를 씁니다([InnoDB 물리 구조](https://dev.mysql.com/doc/refman/8.4/en/innodb-physical-structure.html)).

## 2. B-Tree가 아니라 B+Tree인 이유

이름이 비슷해서 같은 걸로 취급되지만, 실무에서 체감되는 차이는 셋입니다. 핵심은 **데이터를 리프에만 두느냐**입니다.

| | B-Tree | B+Tree |
|---|---|---|
| 데이터 위치 | 내부 노드에도 있음 | 리프에만 |
| 리프 간 연결 | 없음 | 양방향 연결 |
| 조회 비용 | 운 좋으면 루트에서 끝 | 항상 리프까지 |

**첫째, 팬아웃.** 내부 노드에 데이터가 없으면 그 자리에 `키 + 자식 페이지 번호`만 들어갑니다. 항목이 작아지니 페이지 한 장에 더 많이 들어가고, 갈래가 넓어지고, 깊이가 줄어듭니다. 1절 표의 "수백 개"가 여기서 나옵니다.

**둘째, 범위 스캔.** 리프끼리 연결돼 있어서 `BETWEEN`이나 `ORDER BY ... LIMIT`은 시작점만 찾고 옆으로 걸어가면 끝납니다. B-Tree라면 다음 키를 찾을 때마다 트리를 오르내려야 합니다. **인덱스가 범위 조회에 쓰이는 근거는 정렬이 아니라 이 연결 리스트입니다.**

**셋째, 예측 가능성.** 모든 조회가 반드시 리프까지 내려가므로 응답 시간이 균일합니다. 운 좋게 빠른 경우가 없는 대신 운 나쁘게 느린 경우도 없습니다. 지연시간 분포의 꼬리를 관리해야 하는 온라인 서비스에서는 평균보다 이쪽이 중요합니다.

## 3. 페이지 한 장 안에서 벌어지는 일

트리 이야기는 여기까지가 흔한 설명입니다. 그런데 리프 페이지 한 장에 레코드가 수백 개 들어간다면, **그 안에서는 어떻게 찾을까요?** 순서대로 훑으면 페이지 하나에서 수백 번 비교입니다.

### 3-1. 레코드는 물리적으로 정렬돼 있지 않습니다

먼저 오해 하나를 걷어내야 합니다. 페이지 안의 레코드는 키 순서대로 나란히 놓여 있지 않습니다. **삽입된 순서대로 쌓이고, 키 순서는 단일 연결 리스트로 유지합니다.**

이유는 삽입 비용입니다. 물리적으로 정렬해두면 중간에 레코드 하나를 넣을 때마다 뒤쪽 전부를 밀어야 합니다. 16KB를 통째로 memmove 하는 셈입니다. 연결 리스트라면 포인터 두 개만 고치면 끝납니다.

리스트의 양 끝에는 `infimum`과 `supremum`이라는 시스템 레코드가 페이지마다 고정 위치에 있습니다. infimum은 그 페이지의 어떤 키보다 작은 값이고 supremum은 어떤 키보다 큰 값입니다. 스캔의 고정된 시작점과 끝점 역할을 합니다.

```text
infimum → [레코드] → [레코드] → [레코드] → ... → supremum
          (키 오름차순으로 연결. 물리 배치 순서와는 무관)
```

### 3-2. 그래서 페이지 디렉터리가 있습니다

연결 리스트는 이진 탐색이 안 됩니다. 그래서 페이지 끝쪽에 **페이지 디렉터리(Page Directory)** 가 붙습니다. 2바이트 오프셋 슬롯의 배열이고, 슬롯은 키 순서로 정렬돼 있습니다.

중요한 건 밀도입니다. **모든 레코드에 슬롯을 주지 않고, 레코드 4~8개마다 하나씩 둡니다.** infimum과 supremum에는 항상 슬롯이 있습니다([InnoDB 인덱스 페이지의 물리 구조 — jcole, 비공식 내부 분석](https://blog.jcole.us/2013/01/07/the-physical-structure-of-innodb-index-pages/)).

탐색은 두 단계입니다.

1. 슬롯 배열에 이진 탐색 → 찾는 키가 속한 그룹을 특정
2. 그 그룹 안에서 연결 리스트를 최대 7~8칸 순회

디렉터리를 촘촘히 두면 2단계가 짧아지지만 디렉터리가 커져 사용자 레코드가 들어갈 공간을 먹습니다. 4~8개는 그 절충입니다. 정렬된 배열의 탐색 속도와 연결 리스트의 삽입 속도를 함께 가져가는 구조입니다.

### 3-3. 조회 하나의 전체 경로

정리하면 인덱스 조회는 이렇게 흘러갑니다.

```text
1. 데이터 딕셔너리에서 인덱스의 루트 페이지 번호를 얻는다
2. 루트 페이지 로드 → 페이지 디렉터리 이진 탐색 → 그룹 안 순회 → 자식 페이지 번호
3. 2번을 리프에 닿을 때까지 반복 (깊이만큼, 보통 2~3회)
4. 리프 페이지 → 페이지 디렉터리 이진 탐색 → 레코드 확정
5. 범위 조회면 리프 링크를 따라 옆 페이지로 계속
6. 세컨더리 인덱스이고 필요한 컬럼이 없으면 → 기본 키로 클러스터형 인덱스를 다시 1번부터
```

**"페이지 사이에서 한 번, 페이지 안에서 한 번" 두 겹의 이진 탐색입니다.** 6번의 반복 비용은 `day17-why-index.md`에서 다뤘습니다.

## 4. 왜 해시가 아닌가

등치 조회만 놓고 보면 해시가 이깁니다. 트리를 내려갈 필요 없이 한 번에 갑니다. PostgreSQL 진영의 측정에서도 등치 조회는 해시 인덱스가 B-Tree보다 빠르게 나옵니다([EnterpriseDB — Are Hash Indexes Faster than Btree Indexes?](https://www.enterprisedb.com/postgres-tutorials/are-hash-indexes-faster-btree-indexes)).

그런데 해시는 순서를 버립니다. 순서를 버리면 같이 사라지는 것들이 있습니다.

- 범위 조회 (`>`, `BETWEEN`)
- `ORDER BY` 없이 정렬된 결과 얻기
- 전방 일치 (`LIKE 'seoul%'`)
- `MIN`/`MAX`를 스캔 없이 얻기
- 복합 인덱스의 왼쪽 접두사 활용

PostgreSQL의 해시 인덱스는 **단일 컬럼만 가능하고, 등치 검색만 지원하며, 유니크 제약을 걸 수 없습니다.** 반면 B-Tree 연산자 클래스는 `<`, `<=`, `=`, `>=`, `>` 다섯 개를 제공하고 전순서를 보장합니다([PostgreSQL 17 — B-Tree Indexes](https://www.postgresql.org/docs/17/btree.html)).

목록 API에 정렬과 페이지네이션이 붙는 순간, 그리고 조인 조건에 범위가 들어가는 순간 해시는 후보에서 빠집니다. **범용 인덱스는 B+Tree여야 하고, 해시는 특수 목적입니다.**

### 4-1. InnoDB의 절충 — 적응형 해시 인덱스

InnoDB는 둘 중 하나를 고르지 않고 얹었습니다. **적응형 해시 인덱스(AHI, Adaptive Hash Index)** 는 인덱스 검색 패턴을 관찰하다가 자주 접근되는 인덱스 페이지에 대해 키 접두사로 해시 인덱스를 자동으로 만듭니다. 그러면 그 키에 대해서는 트리를 내려가지 않고 바로 갑니다([Adaptive Hash Index](https://dev.mysql.com/doc/refman/8.4/en/innodb-adaptive-hash.html)).

- 기본값 켜짐. `innodb_adaptive_hash_index`로 제어합니다.
- 데이터가 대부분 메모리에 들어가는 워크로드에서 효과가 큽니다.
- `LIKE`와 `%` 와일드카드를 쓰는 쿼리는 혜택을 거의 못 받습니다.
- **동시 조인이 많은 워크로드에서는 AHI 접근 자체가 경합 지점이 됩니다.** 그래서 파티션을 나눠 각각 래치를 따로 씁니다. `innodb_adaptive_hash_index_parts`의 기본값은 8이고 최대 512입니다.

문서 자체가 "켜고 끄고 각각 벤치마크해서 판단하라"고 권합니다. 기본값이 켜짐이라고 해서 항상 이득인 기능이 아니라는 뜻입니다(9절 함정 2).

## 5. 정렬이 공짜가 되는 지점

리프가 정렬돼 있다는 사실은 `WHERE`보다 `ORDER BY`에서 더 크게 돌아옵니다. 인덱스 순서와 정렬 순서가 맞으면 `filesort`가 통째로 사라지고, `LIMIT 20`은 리프에서 20건만 읽고 끝냅니다.

문제는 **방향이 섞일 때**입니다. `ORDER BY grade ASC, score DESC` 같은 조건은 오름차순 인덱스 하나로는 정렬 없이 처리할 수 없습니다.

MySQL 8.0부터 **내림차순 인덱스**를 지원합니다. 키 값을 내림차순으로 저장해서, 역방향으로 읽어야 했을 스캔을 정방향 스캔으로 바꿉니다([Descending Indexes](https://dev.mysql.com/doc/refman/8.4/en/descending-indexes.html)).

```sql
CREATE TABLE student_scores (
    student_id  BIGINT      NOT NULL AUTO_INCREMENT,
    grade       TINYINT     NOT NULL,
    score       INT         NOT NULL,
    PRIMARY KEY (student_id),
    INDEX idx_grade_score (grade ASC, score DESC)
) ENGINE = InnoDB;

-- filesort 없이 처리됩니다
SELECT student_id, score
FROM student_scores
WHERE grade = 2
ORDER BY grade ASC, score DESC
LIMIT 20;
```

제약도 분명합니다.

- InnoDB에서만, `BTREE` 인덱스에서만 지원합니다. `HASH`, `FULLTEXT`, `SPATIAL`은 불가입니다.
- `GROUP BY` 없는 `MIN()`/`MAX()` 최적화에는 쓰이지 않습니다.
- 내림차순 컬럼이 포함된 세컨더리 인덱스는 체인지 버퍼링을 지원하지 않습니다(9절 함정 3).

`EXPLAIN`의 `Extra`에 `Backward index scan`이 보이면 내림차순 인덱스 없이 역방향으로 읽고 있다는 신호입니다. 단일 컬럼 정렬이라면 이 역방향 스캔으로 충분한 경우가 많습니다. 내림차순 인덱스가 실제로 값을 하는 건 **방향이 섞인 다중 컬럼 정렬**입니다.

## 6. 리프에서 걸러내기 — Index Condition Pushdown

3-3의 6번, 즉 클러스터형 인덱스를 다시 타는 랜덤 접근이 세컨더리 인덱스 조회 비용의 대부분입니다. 그 횟수 자체를 줄이는 최적화가 **Index Condition Pushdown(ICP)** 입니다.

ICP가 없으면 이렇습니다.

1. 스토리지 엔진이 인덱스에서 후보를 찾고
2. **후보마다 전체 행을 읽어서 서버에 올리고**
3. 서버가 `WHERE`를 평가해서 버립니다

ICP가 있으면 2번 전에 한 단계가 끼어듭니다. **인덱스 컬럼만으로 판정 가능한 조건을 스토리지 엔진이 먼저 평가하고, 통과한 것만 행을 읽습니다**([Index Condition Pushdown](https://dev.mysql.com/doc/refman/8.4/en/index-condition-pushdown-optimization.html)).

```sql
-- INDEX idx_zip_last (zipcode, lastname, firstname) 가 있을 때
SELECT * FROM member_profiles
WHERE zipcode = '06236'
  AND lastname LIKE '%kim%';
```

`lastname LIKE '%kim%'`은 앞에 `%`가 있어 인덱스로 범위를 좁히지 못합니다. 하지만 `lastname`은 인덱스 안에 **값으로 들어 있으므로** 리프에서 바로 판정할 수 있습니다. 우편번호로 좁힌 후보가 3만 건이고 그중 이름 조건을 통과하는 게 40건이라면, 클러스터형 인덱스 접근이 3만 번에서 40번으로 줄어듭니다.

- 적용 대상: `range`, `ref`, `eq_ref`, `ref_or_null` 접근 방식
- **InnoDB에서는 세컨더리 인덱스에만** 적용됩니다. 클러스터형 인덱스는 이미 전체 레코드를 들고 있으니 의미가 없습니다.
- `EXPLAIN`의 `Extra`에 `Using index condition`으로 찍힙니다. `Using index`(커버링 인덱스)와는 다릅니다. ICP는 결국 행을 읽습니다.
- 기본 활성화이고 `optimizer_switch`의 `index_condition_pushdown`으로 끕니다.

**같은 인덱스인데 어떤 조건을 어디에 쓰느냐로 접근 횟수가 세 자릿수 차이 납니다.** 인덱스에 컬럼을 하나 더 넣는 판단은 "그 컬럼으로 범위를 좁힐 수 있는가"뿐 아니라 "리프에서 걸러낼 수 있는가"도 근거가 됩니다.

## 7. 키 길이가 트리 모양을 정합니다

팬아웃은 `페이지 크기 ÷ 항목 크기`입니다. **키가 길면 팬아웃이 줄고, 팬아웃이 줄면 깊이가 늘고, 깊이가 늘면 모든 조회가 페이지를 한 장 더 읽습니다.** 게다가 세컨더리 인덱스 리프에는 기본 키가 복제되므로, 긴 기본 키의 비용은 인덱스 전체가 나눠 냅니다.

InnoDB의 한계선입니다([InnoDB 제한 사항](https://dev.mysql.com/doc/refman/8.4/en/innodb-limits.html)).

| 항목 | 값 |
|---|---|
| 인덱스 키 접두사 최대 길이 (DYNAMIC / COMPRESSED) | 3072바이트 |
| 인덱스 키 접두사 최대 길이 (REDUNDANT / COMPACT) | 767바이트 |
| 인덱스 하나의 최대 컬럼 수 | 16개 |
| 테이블당 세컨더리 인덱스 최대 수 | 64개 |

페이지 크기가 8KB면 키 길이 한도는 1536바이트, 4KB면 768바이트로 같이 줄어듭니다. 한도가 페이지 크기에 연동된다는 사실 자체가 **이 한도의 정체가 "한 페이지에 최소 몇 개는 들어가야 트리가 성립한다"** 임을 말해줍니다.

`utf8mb4`의 `VARCHAR(255)`는 최대 1020바이트입니다. 이런 컬럼 세 개로 복합 인덱스를 만들면 3072바이트를 넘겨 에러가 납니다. PostgreSQL도 비슷한 이유로 인덱스 엔트리가 **페이지의 약 1/3을 넘을 수 없습니다**([PostgreSQL 17 — B-Tree Indexes](https://www.postgresql.org/docs/17/btree.html)).

참고로 PostgreSQL 17은 B-Tree **중복 제거(deduplication)** 가 기본 활성화입니다. 같은 키가 반복되면 키를 한 번만 저장하고 TID 배열을 붙이는 방식이라 중복 값이 많은 인덱스의 크기가 크게 줄어듭니다. 다만 `numeric`, `jsonb`, `float4`/`float8`, 비결정적 콜레이션 문자열, `INCLUDE` 인덱스에서는 쓸 수 없습니다.

## 8. 트리는 시간이 지나면 헐거워집니다

인덱스 페이지 채움률은 삽입 순서가 정합니다. 순차 삽입이면 페이지가 **약 15/16까지** 차고, 무작위 삽입이면 **1/2에서 15/16 사이**로 찹니다([InnoDB 물리 구조](https://dev.mysql.com/doc/refman/8.4/en/innodb-physical-structure.html)). 여기까지는 `day17-why-index.md`에서 다뤘습니다.

반대 방향도 있습니다. **페이지 병합**입니다.

행을 삭제하거나 `UPDATE`로 행이 짧아져서 페이지 채움률이 `MERGE_THRESHOLD` 아래로 떨어지면, InnoDB는 이웃 페이지와 병합을 시도합니다. **기본값은 50입니다**([인덱스 페이지 병합 임계값 설정](https://dev.mysql.com/doc/refman/8.4/en/index-page-merge-threshold.html)). 지정 가능한 범위는 1~50입니다.

기본값 50에는 알려진 부작용이 있습니다. 50%에서 병합하면 합쳐진 페이지가 곧 다시 가득 차고, 그러면 다시 분할됩니다. **병합과 분할이 번갈아 반복되는 진동**입니다. 문서는 이때 임계값을 낮추라고 안내합니다. 대신 너무 낮추면 페이지가 비어 있는 채로 남아 공간을 낭비합니다.

실제로 진동이 일어나는지는 카운터로 확인합니다.

```sql
SELECT NAME, COUNT
FROM INFORMATION_SCHEMA.INNODB_METRICS
WHERE NAME LIKE '%index_page_merge%';
-- index_page_merge_attempts / index_page_merge_successful
```

```sql
-- 테이블 단위로 조정 (개별 인덱스 설정이 테이블 설정보다 우선합니다)
ALTER TABLE student_scores COMMENT = 'MERGE_THRESHOLD=40';
```

인덱스를 처음 만들 때의 채움 정도는 `innodb_fill_factor`로 조절합니다. 100으로 두면 클러스터형 인덱스 페이지의 1/16을 비워 두고, 80이면 20%를 비웁니다. 다만 문서는 이 값을 **엄격한 한계가 아니라 힌트**로 해석한다고 명시합니다([정렬된 인덱스 빌드](https://dev.mysql.com/doc/refman/8.4/en/sorted-index-builds.html)).

## 9. 함정

### 함정 1 — 수천만 행을 지웠는데 인덱스 크기가 그대로입니다

- **증상**: 오래된 로그 행을 대량 삭제했습니다. 디스크 사용량이 거의 안 줄었고, 조회 속도도 기대만큼 안 빨라졌습니다.
- **원인**: 두 가지가 겹칩니다. 첫째, 삭제로 페이지가 헐거워져도 채움률이 `MERGE_THRESHOLD`(기본 50%)를 깨지 않으면 병합이 일어나지 않습니다. 페이지 수는 그대로고 안이 비었을 뿐입니다. 둘째, 페이지 수가 그대로면 **스캔해야 할 페이지 수도 그대로**입니다. 8절에서 말한 대로 비용의 단위는 행이 아니라 페이지입니다.
- **해법**: 인덱스를 재구축해야 공간이 회수됩니다(`OPTIMIZE TABLE`, 또는 `ALTER TABLE ... ENGINE=InnoDB`). 다만 큰 테이블에서는 비싸고 시간이 오래 걸리는 작업이라 무심코 운영 중에 실행할 게 아닙니다. 애초에 삭제가 반복되는 테이블이라면 파티셔닝으로 파티션째 드롭하는 편이 근본적입니다. 재구축 전후로 `INNODB_METRICS`의 병합 카운터를 비교하면 임계값 조정이 필요한지 판단할 수 있습니다.

### 함정 2 — CPU는 남는데 동시성을 올려도 처리량이 안 늘어납니다

- **증상**: 커넥션을 늘려도 TPS가 어느 선에서 평평해집니다. CPU 사용률도 디스크도 여유가 있습니다. 느린 쿼리 로그에는 특별한 게 없습니다.
- **원인**: 후보 중 하나가 적응형 해시 인덱스입니다. 문서가 명시하듯 **다중 동시 조인 같은 워크로드에서는 AHI 접근이 경합 지점**이 됩니다. 이득을 보려고 켜둔 기능이 병목이 되는 상황이고, 쿼리 단위로는 안 보이니 찾기 어렵습니다. `SHOW ENGINE INNODB STATUS`의 `SEMAPHORES` 섹션에 대기가 쌓이는지 봅니다.
- **해법**: `innodb_adaptive_hash_index_parts`를 올려 래치를 분산하거나(기본 8, 최대 512), `innodb_adaptive_hash_index`를 끄고 같은 부하를 다시 겁니다. **추정하지 말고 켠 상태와 끈 상태를 각각 측정합니다.** 문서의 권고가 그것입니다. <!-- TODO: SEMAPHORES 출력에서 AHI 경합을 특정하는 정확한 판별 문구는 버전마다 달라 확인 필요 -->

### 함정 3 — 버전을 올렸더니 결론이 뒤집힌 경우

- **증상**: 내림차순 인덱스를 추가하니 정렬 쿼리는 빨라졌는데 대량 `INSERT` 배치가 느려졌습니다. MySQL 8.0에서 겪은 일입니다. 그런데 8.4로 올린 뒤 같은 비교를 하니 차이가 사라졌습니다.
- **원인**: 체인지 버퍼는 세컨더리 인덱스 페이지가 버퍼 풀에 없을 때 변경을 모아뒀다가 나중에 병합하는 구조입니다. 그런데 **내림차순 컬럼이 포함된 세컨더리 인덱스는 체인지 버퍼링을 지원하지 않습니다**([Change Buffer](https://dev.mysql.com/doc/refman/8.4/en/innodb-change-buffer.html)). 8.0에서는 이게 실제 손해였습니다. MySQL 8.4에서는 **`innodb_change_buffering`의 기본값이 `none`** 으로 바뀌어서, 기본 설정이라면 애초에 아무 인덱스도 체인지 버퍼를 쓰지 않습니다. 잃을 게 없어진 겁니다.
- **해법**: 인덱스 관련 지식은 **엔진 버전과 기본값에 묶여 있다**는 걸 전제로 다룹니다. 블로그 글의 결론을 그대로 가져오기 전에 그 글이 어느 버전 기준인지 봅니다. 그리고 내림차순 인덱스는 방향이 섞인 다중 컬럼 정렬에만 씁니다. 단일 컬럼 정렬은 역방향 스캔으로 처리됩니다.

### 함정 4 — 인덱스를 다시 만들면 빨라지는데, 몇 주 지나면 원래대로입니다

- **증상**: 재구축 직후에는 빠릅니다. 몇 주 뒤 같은 쿼리가 다시 느려집니다. 데이터 양도 쿼리도 그대로입니다. 그래서 재구축을 정기 작업으로 걸어둡니다.
- **원인**: 인덱스 팽창입니다. 정렬된 인덱스 빌드는 페이지를 아래에서부터 꽉 채워 만듭니다. 그 뒤 무작위 삽입과 삭제가 쌓이면서 분할과 병합이 반복되고, 페이지 채움률이 15/16에서 절반 근처로 내려갑니다. **같은 행 수를 담는 데 페이지가 두 배 필요해지면 읽을 페이지도 두 배가 되고, 버퍼 풀에 들어가는 비율은 절반이 됩니다.** 재구축은 이걸 되돌리므로 효과는 진짜지만 원인은 그대로입니다.
- **해법**: 정기 재구축은 증상 억제입니다. 원인부터 봅니다. 기본 키가 무작위(랜덤 UUID 등)라면 순차적인 값으로 바꾸는 것이 가장 크게 듭니다. 삭제가 많은 테이블이면 `MERGE_THRESHOLD`를 낮춰 진동을 줄입니다. 재구축을 꼭 해야 한다면 `innodb_fill_factor`를 낮춰 빌드해서, 다음 팽창까지의 여유를 미리 확보합니다.

## 10. 참고자료

- [The Physical Structure of an InnoDB Index](https://dev.mysql.com/doc/refman/8.4/en/innodb-physical-structure.html) — B-tree 구조, 16KB 페이지, 15/16 채움률
- [The physical structure of InnoDB index pages — jcole](https://blog.jcole.us/2013/01/07/the-physical-structure-of-innodb-index-pages/) — 3절 페이지 디렉터리·infimum/supremum. 공식 문서가 아닌 내부 구조 분석 자료입니다
- [Adaptive Hash Index](https://dev.mysql.com/doc/refman/8.4/en/innodb-adaptive-hash.html) — 4-1, 함정 2
- [Descending Indexes](https://dev.mysql.com/doc/refman/8.4/en/descending-indexes.html) — 5절
- [Index Condition Pushdown Optimization](https://dev.mysql.com/doc/refman/8.4/en/index-condition-pushdown-optimization.html) — 6절
- [InnoDB Limits](https://dev.mysql.com/doc/refman/8.4/en/innodb-limits.html) — 7절 키 길이·컬럼 수 한계
- [Configuring the Merge Threshold for Index Pages](https://dev.mysql.com/doc/refman/8.4/en/index-page-merge-threshold.html) — 8절, 함정 1
- [Sorted Index Builds](https://dev.mysql.com/doc/refman/8.4/en/sorted-index-builds.html) — `innodb_fill_factor`
- [Change Buffer](https://dev.mysql.com/doc/refman/8.4/en/innodb-change-buffer.html) — 함정 3
- [PostgreSQL 17 — B-Tree Indexes](https://www.postgresql.org/docs/17/btree.html) — 연산자 클래스, 중복 제거, 엔트리 크기 한계
- [EnterpriseDB — Are Hash Indexes Faster than Btree Indexes?](https://www.enterprisedb.com/postgres-tutorials/are-hash-indexes-faster-btree-indexes) — 4절 등치 조회 비교
- `day17-why-index.md` — 페이지 단위 비용, 클러스터형/세컨더리 인덱스, 풀 스캔이 이기는 구간
- `day15-pagination-api.md` — 리프 연결 리스트를 그대로 쓰는 커서 페이지네이션
