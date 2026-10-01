# RDS를 쓴다는 것은 무엇을 넘기고 무엇을 남기는가

> 이 문서가 답할 질문: **RDS로 DB를 띄우면 운영 책임 중 정확히 어디까지가 AWS로 넘어가고, 무엇이 내 손에 남는가?**
>
> 기준: Amazon RDS 사용자 가이드 (2026년 10월 확인). 인스턴스 클래스 선택은 `day40-ec2-sizing.md`, 배포 중 커넥션 처리는 `day18-graceful-shutdown.md`, 접근 제어는 `day22-sg-vs-nacl.md`와 이어집니다.

## 1. RDS는 무엇을 대신해주는가

RDS는 **관계형 데이터베이스의 운영 작업 일부를 API 호출로 바꿔주는 서비스**입니다. 서버를 빌려주는 게 아니라, "백업을 돌린다", "패치를 적용한다", "표준 서버로 넘어간다" 같은 행위를 버튼과 파라미터로 바꿔줍니다.

여기서 중요한 건 **바뀐 것이 "작업의 주체"가 아니라 "작업의 형태"**라는 점입니다. 백업은 여전히 내 책임입니다. 다만 책임의 내용이 "백업 스크립트를 짜고 cron에 걸고 복구를 검증하는 일"에서 **"보존 기간이라는 숫자 하나를 제대로 정하는 일"**로 바뀝니다.

> 이걸 "AWS가 알아서 해준다"로 읽으면 사고가 납니다. 작업량은 1/100로 줄었지만, 그 한 줄 설정이 틀렸을 때의 파급력은 그대로입니다. 백업 보존 기간을 `0`으로 둔 인스턴스는 **아무 경고 없이 잘 돌아갑니다.** 지난 화요일 데이터가 필요해지는 날까지는요.
>
> 더 고약한 건 반대 방향입니다. RDS는 내가 요청하지 않은 일도 합니다. OS 보안 패치가 필요하면 **내가 정하지 않은 시각에** 유지관리 창에서 재시작합니다. 넘긴 것은 작업만이 아니라 **통제권**입니다.

## 2. 경계는 세 칸으로 나뉩니다

둘로 나누면(AWS 책임 / 내 책임) 틀립니다. 실무에서 사고가 나는 지점은 대부분 세 번째 칸입니다.

| | 내용 | 내가 할 일 |
|---|---|---|
| **완전히 넘어감** | 호스트 하드웨어, 하이퍼바이저, OS 설치, 엔진 바이너리 설치, 스토리지 복제, 스냅샷 물리 저장 | 없음 |
| **반쪽만 넘어감** | 백업, 패치, 페일오버, 설정 변경, 모니터링 | AWS가 **실행**하고, 내가 **정책과 시점을 정하고 결과를 확인** |
| **전혀 안 넘어감** | 스키마, 인덱스, 쿼리, 커넥션 풀, 트랜잭션 설계, 계정·권한, 데이터 정합성 | 전부 |

세 번째 칸은 직관적입니다. 인덱스를 AWS가 대신 짜주지 않는다는 걸 모르는 사람은 없습니다.

문제는 두 번째 칸입니다. **"자동"이라는 단어가 "내가 신경 쓸 필요 없음"으로 읽히기 때문입니다.** 자동 백업은 보존 기간을 내가 정해야 자동이고, 자동 페일오버는 애플리케이션이 커넥션을 다시 맺을 수 있어야 자동입니다.

### 2-1. "자동"의 실제 의미

| 기능 | 자동으로 되는 부분 | 내가 안 하면 안 되는 부분 |
|---|---|---|
| 자동 백업 | 스냅샷 생성, 트랜잭션 로그 업로드 | 보존 기간 설정, 복구 리허설 |
| 자동 페일오버 | 표준 인스턴스 승격, DNS 레코드 교체 | 커넥션 재수립, DNS 캐시 TTL, 타임아웃 |
| 자동 패치 | 패치 적용 | 유지관리 창 시각 지정, 다운타임 감수 |
| 자동 마이너 버전 업그레이드 | 버전 올리기 | 올라간 버전에서 내 쿼리가 도는지 확인 |

## 3. 넘긴 대가 — 할 수 없게 되는 것들

운영을 넘기면 **운영에 쓰이던 권한도 같이 넘어갑니다.** 이게 RDS를 쓸지 말지 가르는 실질적 기준입니다.

**OS에 접근할 수 없습니다.** SSH가 없습니다. `top`을 칠 수 없고, 서버의 로그 파일을 직접 `tail`할 수 없습니다. 대신 CloudWatch 메트릭, Enhanced Monitoring, RDS 콘솔의 로그 뷰어를 씁니다.

**마스터 계정은 슈퍼유저가 아닙니다.** RDS for PostgreSQL의 마스터 유저는 `NOSUPERUSER`로 생성되고, 대신 `rds_superuser` 역할을 받습니다. ([rds_superuser 역할](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Appendix.PostgreSQL.CommonDBATasks.Roles.rds_superuser.html)) MySQL에서도 마스터 유저는 `SUPER` 권한을 받지 못합니다. ([마스터 유저 권한](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.MasterAccounts.html)) 즉 `my.cnf`를 고치거나 임의 확장을 설치하는 식의 접근은 막혀 있습니다.

**설정은 파라미터 그룹으로만 바꿉니다.** 그리고 기본 파라미터 그룹은 **수정할 수 없습니다.** 커스텀 그룹을 만들어 붙이는 게 유일한 경로입니다. ([파라미터 그룹 개요](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/parameter-groups-overview.html))

파라미터는 두 종류로 나뉘고, 이 구분이 "설정을 바꿨는데 안 먹는" 사고의 원인입니다.

- **동적(dynamic) 파라미터** — 저장하면 재시작 없이 즉시 적용됩니다.
- **정적(static) 파라미터** — 저장해도 **수동 재시작 전까지는 적용되지 않습니다.**

```bash
# 파라미터가 정적인지 동적인지는 ApplyType으로 확인합니다
aws rds describe-engine-default-parameters \
    --db-parameter-group-family mysql8.0 \
    --query "EngineDefaults.Parameters[?ParameterName=='max_connections'].[ParameterName,ApplyType]"
```

## 4. 책임이 실제로 갈리는 세 순간

문서로 읽으면 다 당연합니다. 실제로 갈리는 지점만 봅니다.

### 4-1. 유지관리 창 — AWS가 내 DB를 재시작합니다

유지관리 창은 **주 1회, 30분 구간**입니다. 생성 시 지정하지 않으면 리전별 8시간 블록 안에서 **무작위로 배정**됩니다. ([유지관리](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_UpgradeDBInstance.Maintenance.html)) 서울 리전의 블록은 `13:00–21:00 UTC`, 즉 한국시간 밤 10시부터 다음날 아침 6시 사이입니다.

OS 업데이트는 두 종류입니다.

- **선택(optional)** — 상태가 `available`이고 적용 날짜가 없습니다. RDS가 **자동으로 적용하지 않습니다.**
- **필수(mandatory)** — 상태가 `required`이고 적용 날짜가 있습니다. 그 날짜가 지나면 **유지관리 창에서 자동으로 적용됩니다.**

OS 업데이트는 보통 **10분 정도** 걸립니다. 그리고 창을 계속 미뤄도 소용없습니다. 공식 문서가 명시합니다 — 필수 업그레이드를 피하려고 유지관리 창을 반복해서 바꾸면, RDS는 적용 기한이 지난 뒤 **선호 창 바깥에서도** 업그레이드를 적용할 수 있습니다.

Multi-AZ 배포라면 OS 패치는 다운타임 없이 흐릅니다.

```
표준 인스턴스 패치 → 표준을 주 인스턴스로 승격 → 옛 주 인스턴스 패치
```

이때 1분 미만의 페일오버가 한 번 발생합니다. **엔진 버전 업그레이드는 다릅니다.** Multi-AZ여도 주·표준 인스턴스를 동시에 수정하므로 **업그레이드가 끝날 때까지 다운타임**입니다.

### 4-2. 페일오버 — 끊기는 커넥션은 내가 처리합니다

Multi-AZ DB 인스턴스의 페일오버는 **보통 60~120초**입니다. 큰 트랜잭션이나 긴 복구 과정이 있으면 더 걸립니다. ([페일오버](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.Failover.html))

핵심은 **페일오버가 엔드포인트의 DNS 레코드를 바꾸는 방식으로 동작**한다는 점입니다. IP가 바뀝니다. 그래서 **기존 커넥션은 전부 다시 맺어야 합니다.** 여기서 두 가지가 내 책임으로 떨어집니다.

**첫째, DNS 캐시.** JVM은 호스트명 해석 결과를 캐시합니다. 일부 Java 구성에서는 TTL이 "JVM을 재시작할 때까지 절대 갱신하지 않음"으로 설정돼 있습니다. 그러면 페일오버가 끝나도 애플리케이션은 **죽은 IP로 계속 접속을 시도합니다.** AWS 권고는 60초 이하입니다.

```java
// 애플리케이션 초기화 시점 — 네트워크 연결이 생기기 전에 설정합니다
public static void main(String[] args) {
    java.security.Security.setProperty("networkaddress.cache.ttl", "60");
    SpringApplication.run(OrderApiApplication.class, args);
}
```

**둘째, 소켓 타임아웃.** 페일오버 중 주 인스턴스는 "거절"하지 않고 **응답하지 않습니다.** 타임아웃이 없으면 요청 스레드가 그대로 매달립니다. 60초 동안 들어온 요청이 전부 스레드를 붙들면, DB 장애가 **애플리케이션 전체 장애**로 번집니다.

```yaml
# application.yml — Spring Boot 3.x + HikariCP + MySQL Connector/J 8.x 기준
spring:
  datasource:
    url: jdbc:mysql://orders-db.example.com:3306/orders?connectTimeout=3000&socketTimeout=10000
    hikari:
      connection-timeout: 3000     # 풀에서 커넥션을 못 받으면 3초 뒤 실패
      validation-timeout: 2000
      max-lifetime: 600000         # 10분 — 죽은 커넥션을 오래 들고 있지 않게
      keepalive-time: 120000
```

**셋째, 표준 인스턴스는 읽기용이 아닙니다.** Multi-AZ DB 인스턴스 배포의 표준 인스턴스에는 쿼리를 보낼 수 없습니다. Multi-AZ는 가용성을 위한 구성이고, 읽기 부하 분산은 **읽기 전용 복제본이라는 별도 기능**입니다. 반면 Multi-AZ DB 클러스터는 라이터 1대 + **읽기 가능한 리더 2대**를 세 AZ에 두는 다른 구성입니다. ([Multi-AZ DB 클러스터](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/multi-az-db-clusters-concepts.html))

### 4-3. 복구 — 복구는 "되돌리기"가 아니라 "새로 만들기"입니다

자동 백업의 보존 기간은 **0~35일**입니다. 콘솔로 만들면 기본 7일, API나 CLI로 만들면서 지정하지 않으면 **기본 1일**입니다. `0`은 자동 백업을 끈다는 뜻입니다. ([백업 보존 기간](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_WorkingWithAutomatedBackups.BackupRetention.html))

시점 복구(PITR)는 트랜잭션 로그를 S3에 **5분마다** 올리는 방식입니다. 그래서 복구 가능한 최신 시점은 현재보다 몇 분 뒤처져 있고, 그 값은 `LatestRestorableTime`으로 확인합니다. ([시점 복구](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PIT.html))

그리고 가장 오해가 많은 지점입니다. **복구는 원본을 바꾸지 않고 새 DB 인스턴스를 만듭니다.** 새 인스턴스에는 **새 엔드포인트**가 붙습니다. 즉 복구를 끝낸 뒤에도 애플리케이션 설정을 바꾸거나 이름을 바꿔 끼우는 작업이 남습니다. 복구된 인스턴스는 기본적으로 **기본 파라미터 그룹과 기본 옵션 그룹**에 연결되므로, 커스텀 설정을 쓰고 있었다면 그것도 다시 붙여야 합니다.

```bash
# 복구 가능한 범위를 평소에 확인해둡니다 — 장애 중에 처음 보면 늦습니다
aws rds describe-db-instances \
    --db-instance-identifier orders-db \
    --query "DBInstances[0].[BackupRetentionPeriod,LatestRestorableTime,PreferredMaintenanceWindow,PreferredBackupWindow]"
```

## 5. 모니터링도 반쪽만 넘어옵니다

OS 접근을 포기했으니, 서버 안에서 무슨 일이 벌어지는지는 RDS가 내보내주는 것만 볼 수 있습니다. 그런데 그게 **세 개의 서로 다른 기능으로 쪼개져 있고, 기본으로 켜져 있는 건 하나뿐**입니다.

| 보는 수준 | 기능 | 기본 활성 | 어디에 저장되는가 |
|---|---|---|---|
| 하이퍼바이저 관점 | CloudWatch 메트릭 | 켜져 있음 | CloudWatch 메트릭 |
| OS·프로세스 관점 | Enhanced Monitoring | **꺼져 있음** | CloudWatch **Logs** (`RDSOSMetrics` 로그 그룹) |
| 쿼리·대기 이벤트 관점 | Performance Insights | 엔진·버전에 따라 다름 | 전용 저장소 |

기본 CloudWatch의 `CPUUtilization`은 **하이퍼바이저에서 수집**합니다. Enhanced Monitoring은 **DB 인스턴스 안의 에이전트에서 수집**합니다. 그래서 두 값은 일치하지 않고, **인스턴스 클래스가 작을수록 차이가 커집니다.** ([Enhanced Monitoring](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_Monitoring.OS.html))

실무에서 이게 왜 중요한가 하면, "어느 프로세스가 CPU를 쓰는가"를 알고 싶을 때 기본 메트릭에는 **그 정보가 아예 없습니다.** `top`을 칠 수 없는 환경에서 그 질문에 답하는 유일한 수단이 Enhanced Monitoring이고, 그건 **장애가 터진 뒤에 켜도 이미 지난 시점의 데이터를 주지 않습니다.**

Enhanced Monitoring 메트릭은 CloudWatch Logs에 **기본 30일** 보관됩니다. 일반 CloudWatch 메트릭의 보존 정책과 다르다는 점만 기억하면 됩니다. 비용은 CloudWatch Logs 전송·저장 요금으로 붙고, **수집 간격을 짧게 할수록 비용이 올라갑니다.**

그리고 DB 엔진 로그(슬로우 쿼리 로그, 에러 로그)는 **CloudWatch Logs로 내보내기를 명시적으로 켜야** 흘러갑니다. 켜지 않으면 RDS 콘솔에서만 볼 수 있고, 인스턴스를 삭제하면 같이 사라집니다.

## 6. 헷갈리는 경계 — Multi-AZ와 읽기 전용 복제본

이름이 둘 다 "복제"라서 섞이는데, **푸는 문제가 다릅니다.**

| | Multi-AZ DB 인스턴스 | 읽기 전용 복제본 |
|---|---|---|
| 목적 | 가용성 | 읽기 처리량 |
| 사본에 쿼리 | **불가** | 가능 |
| 승격 | 자동 | 수동 |
| 엔드포인트 | 하나 (페일오버 시 DNS 교체) | 복제본마다 별도 |
| 복제 지연 | 애플리케이션에 안 보임 | **애플리케이션이 다뤄야 함** |

"Multi-AZ를 켰으니 읽기 부하도 나눠지겠지"가 가장 흔한 오해입니다. 안 나눠집니다. 반대로 "읽기 복제본이 있으니 장애에도 안전하겠지"도 틀립니다. 승격은 수동이고, 승격하는 순간 그건 더 이상 복제본이 아닙니다.

둘은 **같이 쓰는 구성**입니다. Multi-AZ로 가용성을, 읽기 복제본으로 처리량을 따로 사는 겁니다. 그리고 읽기 복제본을 쓰기 시작하면 복제 지연이라는 새 문제가 생깁니다 — 방금 쓴 데이터가 바로 안 읽히는 문제는 RDS가 풀어주지 않습니다.

## 7. 언제 RDS를 쓰고, 언제 쓰지 않는가

### 7-1. RDS가 맞는 경우

표준적인 관계형 DB가 필요하고, DBA 전담 인력이 없고, OS 수준 커스터마이징이 필요 없는 경우입니다. 대부분의 백엔드 서비스가 여기 들어갑니다.

### 7-2. RDS가 안 맞는 경우

- **OS나 파일시스템에 접근해야 한다** — 특정 네이티브 확장, 커널 파라미터 튜닝, 에이전트 설치가 필요한 경우
- **RDS가 지원하지 않는 엔진·버전이 필요하다**
- **슈퍼유저 권한이 필요한 작업이 설계에 들어 있다**

이 세 경우는 EC2에 직접 설치하는 쪽이 맞습니다. 단, 그 순간 2절의 **두 번째 칸 전체가 내 책임으로 넘어옵니다.** 백업 스크립트, 패치 계획, 페일오버 자동화를 전부 직접 만들어야 합니다.

## 8. 함정

### 8-1. 보존 기간을 바꿨는데 순간 끊겼습니다

- **증상**: 운영 중 백업 보존 기간을 `0`에서 `7`로 바꾸자 커넥션이 전부 끊겼습니다.
- **원인**: 보존 기간을 `0`에서 0이 아닌 값으로, 또는 그 반대로 바꾸면 **중단(outage)이 발생합니다.** 0 → 7은 백업 기능 자체를 켜는 변경이라서 그렇습니다.
- **해법**: 이 변경만은 유지관리 창에 예약해서 적용합니다. 더 좋은 해법은 **생성 시점에 제대로 넣는 것**입니다. CLI나 Terraform으로 만들 때 보존 기간을 명시하지 않으면 1일이 되므로, 생성 코드에서 반드시 지정합니다.

### 8-2. 파라미터를 바꿨는데 반영되지 않습니다

- **증상**: 파라미터 그룹에서 값을 바꾸고 저장했는데 `SHOW VARIABLES`가 옛 값을 보여줍니다. 콘솔의 파라미터 그룹 상태는 `pending-reboot`입니다.
- **원인**: 정적 파라미터입니다. 정적 파라미터는 **수동 재시작 후에 적용됩니다.** 그리고 `pending-reboot` 상태는 **다음 유지관리 창에 자동 재시작을 유발하지 않습니다.** 영원히 기다려도 안 바뀝니다.
- **해법**: 직접 재시작합니다. 새 파라미터 그룹을 인스턴스에 처음 연결한 경우에는 동적 파라미터까지 **재시작 후에야** 적용되므로, 그룹 교체는 항상 재시작을 전제로 계획합니다.

### 8-3. 스토리지를 줄일 수 없습니다

- **증상**: 테스트로 1,000 GiB를 할당했는데 되돌리려니 콘솔에 100 GiB 입력이 거부됩니다.
- **원인**: **할당한 스토리지는 줄일 수 없습니다.** EBS 볼륨의 제약입니다. 늘릴 때도 최소 10% 이상이어야 하고, 24시간 안에 **최대 4번**까지만 변경할 수 있습니다. 변경 후에는 `storage-optimization` 상태가 몇 시간 지속될 수 있고, 그동안은 추가 변경이 막힙니다. ([스토리지 확장](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PIOPS.ModifyingExisting.ScalingUp.html))
- **해법**: 되돌리는 유일한 방법은 **더 작은 스토리지로 새 인스턴스를 만들어 데이터를 옮기는 것**입니다. 그러니 처음에는 작게 잡고, 스토리지 자동 조정(storage autoscaling)으로 상한만 걸어둡니다.

### 8-4. 인스턴스를 지웠더니 백업도 없어졌습니다

- **증상**: 쓰지 않는 인스턴스를 삭제했습니다. 며칠 뒤 그 데이터가 필요해졌는데 자동 백업이 보이지 않습니다.
- **원인**: 삭제 시 **"자동 백업 보존"을 선택하지 않으면 자동 백업은 인스턴스와 함께 삭제됩니다.** 수동 스냅샷은 독립적이어서 남습니다.
- **해법**: 삭제 전 수동 스냅샷을 하나 만듭니다(리전당 최대 100개). 삭제 시에는 최종 스냅샷 생성과 자동 백업 보존을 함께 켭니다. Terraform을 쓴다면 `skip_final_snapshot = true`가 운영 리소스에 들어가 있는지 점검합니다.

### 8-5. 복구해본 적이 없는 백업

- **증상**: 백업이 35일치 쌓여 있는데, 실제 사고 때 복구가 2시간 넘게 걸렸습니다.
- **원인**: PITR은 새 인스턴스를 **만드는** 작업입니다. 그리고 복구 직후 볼륨은 S3에서 블록을 백그라운드로 내려받는 중이어서, 인스턴스가 `available`이 돼도 **성능이 완전하지 않습니다.** 복구 시간은 데이터 크기에 비례하는데, 리허설을 안 하면 이 숫자를 모릅니다.
- **해법**: 분기마다 한 번씩 스테이징에서 PITR을 실제로 실행해 **복구 완료까지 걸린 분(分)을 기록합니다.** 그 숫자가 조직의 실질 RTO입니다. 복구 절차에는 엔드포인트 교체와 파라미터 그룹 재연결까지 포함시킵니다.

### 8-6. 커넥션 상한을 인스턴스 크기가 정합니다

- **증상**: 인스턴스를 작은 클래스로 내렸더니 `Too many connections`가 나기 시작했습니다.
- **원인**: RDS for MySQL의 `max_connections` 기본값은 고정된 숫자가 아니라 **인스턴스 메모리로 계산되는 수식**입니다 — `{DBInstanceClassMemory/12582880}`. ([DB 파라미터 지정](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_ParamValuesRef.html)) 인스턴스 클래스를 바꾸면 커넥션 상한도 따라 바뀝니다. 애플리케이션 풀 크기는 그대로인데 DB 쪽 상한이 내려간 겁니다.
- **해법**: 스케일 다운 전에 `(인스턴스 수 × 풀 최대 크기) + 운영용 여유`를 계산해 새 클래스의 기본값과 비교합니다. 수식을 임의로 올려 상한만 키우면 메모리 부족으로 더 나쁜 장애가 됩니다. 해답은 보통 상한 조정이 아니라 **풀 크기 줄이기** 또는 RDS Proxy입니다.

## 9. 참고자료

- [Amazon RDS 사용자 가이드 — Multi-AZ 페일오버](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/Concepts.MultiAZ.Failover.html)
- [DB 인스턴스 유지관리](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_UpgradeDBInstance.Maintenance.html)
- [백업 소개](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_WorkingWithAutomatedBackups.html) · [시점 복구](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PIT.html)
- [파라미터 그룹 개요](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/parameter-groups-overview.html)
- [Enhanced Monitoring으로 OS 메트릭 보기](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_Monitoring.OS.html)
- [AWS 공동 책임 모델](https://aws.amazon.com/compliance/shared-responsibility-model/)
- 관련 챕터: `day40-ec2-sizing.md` · `day18-graceful-shutdown.md` · `day22-sg-vs-nacl.md`
