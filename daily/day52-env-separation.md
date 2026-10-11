# dev/staging/prod는 무엇을 기준으로 나누는가

> 이 문서가 답할 질문: **환경을 나눈다는 건 설정 파일을 복사하는 일이 아니라 경계를 긋는 일입니다. 그 경계를 어디에, 얼마나 세게 그어야 하는가?**
>
> 기준: AWS 멀티 계정 백서·Spring Boot 4.1 프로필 문서·Terraform CLI 문서 (2026년 10월 확인). <!-- TODO: 프로필 전용 문서에서 `spring.profiles.active`를 못 쓴다는 제약은 4.1 문서에서만 확인했습니다. 2.4 이후 계속 유지된 제약으로 보이지만 3.x 문서로 교차확인이 필요합니다. --> 설정 값을 밖으로 빼는 방법은 `day06-env-variable.md`, 로컬 환경 표준화는 `day24-local-dev-env.md`, 권한 범위는 `day34-iam-least-privilege.md`와 이어집니다.

## 1. 환경은 "설정의 집합"이 아니라 "경계의 집합"입니다

환경 분리의 출발점은 거의 항상 같습니다. `application-dev.yml`과 `application-prod.yml`을 만들고, DB 주소와 로그 레벨을 다르게 적습니다.

이건 **설정 분기**입니다. 환경 분리가 아닙니다. 둘의 차이는 하나로 갈립니다 — **실수했을 때 막아주는 것이 있는가.**

> dev 프로필로 뜬 애플리케이션이 프로덕션 DB에 쓰는 걸 막는 장치가 설정 파일에는 없습니다. 환경변수 이름을 한 글자 틀리거나, 배포 파이프라인에서 프로필 주입이 빠지면 **그냥 돕니다.** 에러도, 경고도 없습니다. 두 환경이 같은 계정·같은 VPC·같은 IAM 역할 아래 있다면, "환경이 나뉘었다"는 사실은 파일명에만 존재합니다.
>
> 반대쪽도 똑같이 아픕니다. 경계를 세게 그어서 staging을 프로덕션과 전혀 다른 모양으로 만들면, staging에서 통과한 배포가 프로덕션에서 터집니다. 이때 staging은 비용만 쓰고 아무것도 보증하지 않습니다.

환경은 **같은 코드가 서로 다른 데이터·자격증명·규모 위에서 도는 독립된 실행 공간**입니다. 독립이라는 단어가 핵심이고, 그 독립을 무엇으로 보장하느냐가 이 문서의 전부입니다.

## 2. 목적이 두 개이고, 서로 반대 방향으로 당깁니다

환경을 나누는 이유는 둘입니다. 보통 한쪽만 생각하기 때문에 설계가 어긋납니다.

| | 목적 | 원하는 것 |
|---|---|---|
| **격리** | dev에서 한 일이 프로덕션에 닿지 않게 | 환경 사이에 길이 없을수록 좋음 |
| **닮음** | 프로덕션에서 터질 일을 먼저 터뜨리게 | 환경이 똑같을수록 좋음 |

이 둘은 같은 방향이 아닙니다. 서로를 깎습니다.

격리를 끝까지 밀면 staging은 다른 계정, 다른 IAM 역할, 다른 엔드포인트, 다른 데이터를 갖습니다. 그러면 **프로덕션에서만 나는 버그**가 생깁니다. 닮음을 끝까지 밀면 프로덕션 데이터를 복제하고 자격증명을 공유합니다. 그러면 격리가 무너집니다.

12 Factor App의 `dev/prod parity`는 이 중 닮음 쪽만 다루면서 간극을 세 가지로 나눕니다 — 시간(코드가 프로덕션에 닿기까지), 사람(짠 사람과 배포하는 사람), 도구(웹 서버·DB·OS가 다름). 특히 백킹 서비스는 어댑터로 가려도 종류와 버전을 다르게 쓰지 말라고 못을 박습니다. ([dev/prod parity](https://12factor.net/dev-prod-parity))

그래서 실무 질문은 "환경을 몇 개 만들까"가 아닙니다. **축마다 격리와 닮음 중 어느 쪽을 택할지**입니다.

## 3. 축마다 따로 결정합니다

| 축 | 기본 선택 | 이유 |
|---|---|---|
| 배포 아티팩트 (jar·이미지) | **닮음 — 하나만** | 환경별로 다시 빌드하면 "staging 통과"가 아무것도 보증하지 않습니다 |
| 백킹 서비스 종류·버전 | **닮음** | H2에서 통과한 쿼리가 MySQL에서 깨집니다 |
| 인프라 코드 | **닮음 (같은 모듈)** | 토폴로지가 갈리면 프로덕션 전용 장애가 생깁니다 |
| 설정 값 | 격리 | |
| 자격증명·시크릿 | 격리 | 공유하는 순간 경계가 사라집니다 |
| 데이터 | 격리 | |
| 네트워크·IAM | 격리 | |
| 규모·쿼터 | 격리 (다름을 인정) | 비용 때문에 같게 만들 수 없습니다 |

정리하면 한 줄입니다. **모양은 닮게, 값은 다르게.**

규모 축만 예외입니다. 여기는 닮게 만들 수 없으므로 "staging으로는 부하 특성을 검증할 수 없다"는 사실을 인정하고 다른 수단(부하 테스트 전용 환경, 프로덕션 카나리)으로 옮기는 게 맞습니다.

### 3-1. 가장 비싼 실수 — 환경별로 다시 빌드하기

```yaml
# ❌ 환경마다 빌드를 다시 돈다 — staging에서 검증한 바이너리가 프로덕션에 가지 않는다
jobs:
  deploy-stage:
    steps:
      - run: ./gradlew bootJar -Pprofile=stage
      - run: docker build -t order-api:stage .
  deploy-prod:
    steps:
      - run: ./gradlew bootJar -Pprofile=prod   # 여기서 다시 빌드
      - run: docker build -t order-api:prod .
```

빌드를 다시 돌면 의존성 해석 결과, 빌드 플러그인 버전, 베이스 이미지 태그가 달라질 수 있습니다. staging에서 통과한 것과 프로덕션에 올라간 것이 **다른 물건**입니다.

```yaml
# ✔️ 한 번 빌드하고 같은 다이제스트를 승격한다
jobs:
  build:
    steps:
      - run: ./gradlew bootJar            # 프로필 무관
      - run: docker build -t ghcr.io/example/order-api:${{ github.sha }} .
      - run: docker push ghcr.io/example/order-api:${{ github.sha }}

  deploy-stage:
    needs: build
    steps:
      - run: ./deploy.sh stage ghcr.io/example/order-api:${{ github.sha }}

  deploy-prod:
    needs: deploy-stage
    steps:
      - run: ./deploy.sh prod ghcr.io/example/order-api:${{ github.sha }}
```

환경 차이는 전부 **런타임 주입**으로 내려갑니다. 빌드 산출물에는 환경이라는 개념이 없어야 합니다.

## 4. 경계의 강도 — 네 단계

격리는 있거나 없는 게 아니라 단계가 있습니다. 위로 갈수록 실수를 더 많이 막아주고, 더 비쌉니다.

```
1. 설정 분기     프로필·환경변수만 다름          → 같은 프로세스, 경계 없음
2. 논리 분리     네임스페이스·태그·키 접두사      → 같은 계정·같은 네트워크
3. 네트워크 분리  VPC를 따로 둠                  → 라우팅 경로 자체가 없음
4. 계정 분리     AWS 계정을 따로 둠              → IAM·쿼터·비용이 끊김
```

1단계는 실수를 전혀 막지 못합니다. 2단계는 오타를 막지만 권한을 막지 못합니다 — dev 자격증명으로 프로덕션 리소스 ARN을 때릴 수 있으면 접두사는 장식입니다. 3단계는 네트워크 경로를 끊습니다. 다만 S3·DynamoDB처럼 네트워크가 아니라 IAM으로 접근하는 리소스는 VPC가 막아주지 않습니다.

### 4-1. 왜 계정이 최종 경계인가

AWS에서 계정이 특별한 이유는 네 가지가 계정 단위로 끊어지기 때문입니다.

**IAM 평가가 끊깁니다.** 크로스 계정 요청은 AWS가 두 번 평가하고, **양쪽 평가가 모두 `Allow`일 때만** 허용됩니다. 요청하는 쪽의 ID 기반 정책과 리소스가 있는 쪽의 리소스 기반 정책이 둘 다 명시적으로 열어줘야 합니다. ([크로스 계정 정책 평가](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic-cross-account.html)) 즉 **기본값이 거부**입니다. 같은 계정 안에서는 정책 하나를 넓게 쓰는 실수로 경계가 뚫리지만, 계정이 다르면 양쪽에서 동시에 실수해야 뚫립니다.

**서비스 쿼터와 API 요청 속도 제한이 계정별로 할당됩니다.** AWS 백서는 이걸 멀티 계정의 이점으로 명시합니다 — 계정을 나누면 쿼터와 제한의 영향 범위가 분산됩니다. ([멀티 계정의 이점](https://docs.aws.amazon.com/whitepapers/latest/organizing-your-aws-environment/benefits-of-using-multiple-aws-accounts.html))

**비용 배분의 기본 단위가 계정입니다.** 같은 백서가 "계정은 AWS 비용이 배분되는 기본 수단"이라고 적습니다. 환경별 비용을 태그로 가르려면 모든 리소스에 태그가 빠짐없이 붙어 있어야 하고, 그건 유지되지 않습니다.

**사고 범위가 갇힙니다.** 한 계정 안의 오설정·폭주 스크립트·유출된 자격증명이 다른 계정의 워크로드로 번지지 않습니다.

AWS가 권장하는 구조는 Workloads OU 안에 프로덕션·비프로덕션 계정을 두고, 실험과 개발용은 Sandbox OU로 분리하는 모양입니다. Sandbox 계정은 **사내 데이터와 프로덕션 리소스 접근이 제한된** 자리입니다. ([권장 OU와 계정](https://docs.aws.amazon.com/whitepapers/latest/organizing-your-aws-environment/recommended-ous-and-accounts.html))

> 경계를 1~2단계에 두면 이런 식으로 터집니다. dev와 프로덕션이 같은 계정일 때, dev에서 돈 부하 테스트가 Lambda 동시 실행 쿼터를 다 먹어서 프로덕션 함수가 스로틀됩니다. 애플리케이션 코드는 멀쩡하고 설정도 멀쩡합니다. 범인은 **배포한 적도 없는 다른 환경**입니다.

## 5. 코드로 보는 구성

### 5-1. 프로필에 기본값을 주지 않습니다

```yaml
# ❌ application.yml — 기본 프로필이 dev
spring:
  profiles:
    active: dev
```

```yaml
# application-dev.yml
spring:
  datasource:
    url: jdbc:mysql://dev-db.internal:3306/orders
```

프로덕션 배포에서 `SPRING_PROFILES_ACTIVE` 주입이 빠지면 어떻게 될까요. 애플리케이션은 **정상 기동합니다.** 헬스체크도 통과합니다. 그리고 프로덕션 트래픽이 dev DB에 주문을 씁니다. 발견은 며칠 뒤 정산이 안 맞을 때입니다.

```yaml
# ✔️ application.yml — 공통 설정만. active 기본값 없음
spring:
  application:
    name: order-api
  datasource:
    url: ${ORDER_DB_URL}          # 기본값 없음 → 없으면 기동 실패
    username: ${ORDER_DB_USER}
    password: ${ORDER_DB_PASSWORD}
```

필수 설정에 기본값을 주지 않는 것이 가장 값싼 방어입니다(`day06-env-variable.md`). 프로필에도 같은 원칙을 적용합니다.

여기에 **활성 프로필 자체를 검증하는 빈**을 하나 두면 "프로필이 둘 켜졌다", "오타 난 프로필이 켜져서 아무 설정도 안 먹었다" 같은 경우까지 기동 시점에 잡힙니다.

```java
@Component
public class ActiveProfileVerifier {

    private static final Set<String> ALLOWED = Set.of("local", "dev", "stage", "prod");

    public ActiveProfileVerifier(Environment environment) {
        List<String> active = List.of(environment.getActiveProfiles());
        if (active.size() != 1 || !ALLOWED.contains(active.get(0))) {
            throw new IllegalStateException(
                    "활성 프로필은 " + ALLOWED + " 중 정확히 하나여야 합니다. 현재: " + active);
        }
    }
}
```

프로필이 여러 개 필요하면 `spring.profiles.group`으로 묶습니다. `--spring.profiles.active=prod` 하나로 `prod`, `proddb`, `prodmq`가 함께 켜집니다.

```yaml
spring:
  profiles:
    group:
      prod:
        - proddb
        - prodmq
```

⚠️ `spring.profiles.active`·`include`·`group`·`default`는 **프로필 전용 문서에서 쓸 수 없습니다.** `application-prod.yml` 안이나 `spring.config.activate.on-profile`로 활성화되는 문서 안에 쓰면 유효하지 않습니다. ([Spring Boot 프로필](https://docs.spring.io/spring-boot/reference/features/profiles.html)) "prod 프로필에서 profile을 더 켜려고 했는데 안 먹는다"의 원인이 대부분 이겁니다.

### 5-2. Terraform — workspace가 아니라 디렉터리

CLI workspace로 환경을 나누는 건 격리가 아닙니다. HashiCorp 문서가 직접 말합니다 — 한 작업 디렉터리의 CLI workspace들은 **같은 backend를 공유**하므로, 접근 제어를 다르게 둬야 하는 배포 단계 격리에는 적합한 수단이 아닙니다. 권장안은 공통 요소를 재사용 모듈로 만들고, 환경마다 **자기 backend를 가진 별도 루트 모듈**을 두는 것입니다. ([Terraform workspaces](https://developer.hashicorp.com/terraform/cli/workspaces))

```
infra/
├── modules/
│   └── order-service/        # 모양을 정의하는 곳 — 여기 한 군데
│       ├── main.tf
│       └── variables.tf
└── envs/
    ├── dev/{backend.tf, main.tf}
    ├── stage/{backend.tf, main.tf}
    └── prod/{backend.tf, main.tf}
```

```hcl
# envs/prod/main.tf — 차이는 전부 변수로만 드러난다
terraform {
  backend "s3" {
    bucket = "example-tfstate-prod"
    key    = "order-service/terraform.tfstate"
    region = "ap-northeast-2"
  }
}

module "order_service" {
  source = "../../modules/order-service"

  environment   = "prod"
  instance_type = "m7i.large"
  min_size      = 3
  db_multi_az   = true
}
```

핵심 규칙 하나입니다. **환경 디렉터리에 리소스를 직접 쓰지 않습니다.** `aws_instance`가 `envs/prod/main.tf`에 들어가는 순간, 그 리소스는 dev에 존재하지 않게 되고 환경 간 모양이 갈라지기 시작합니다.

### 5-3. workspace가 맞는 자리는 따로 있습니다

그럼 workspace는 쓸 데가 없는 기능일까요. 같은 문서가 적합한 용도를 명시합니다 — **변경을 적용해보기 위한 병렬적이고 임시적인 사본**입니다.

여기에 딱 맞는 게 PR마다 띄우는 수명이 짧은 미리보기 환경입니다. 성질이 장기 환경과 다릅니다.

| | 장기 환경 (dev/stage/prod) | 임시 환경 (PR 미리보기) |
|---|---|---|
| 수명 | 무기한 | PR이 닫히면 삭제 |
| 접근 제어 | 환경별로 달라야 함 | dev와 같아도 됨 |
| state | 환경별 backend | dev backend 안에서 workspace로 분기 |

구분 기준은 수명이 아니라 **접근 제어가 달라야 하는가**입니다. 달라야 하면 backend를 쪼개고, 같아도 되면 workspace로 충분합니다. 임시 환경에는 삭제 책임이 따라붙습니다 — PR 머지 시 `destroy`가 자동으로 돌지 않으면, 잊힌 환경이 다음 달 청구서로 돌아옵니다.

## 6. staging은 언제 가치가 있고, 언제 없는가

staging의 가치는 하나뿐입니다. **프로덕션에서 날 문제를 먼저 나게 하는 것.** 그래서 가치는 닮음에 정비례하고, 유지비도 닮음에 정비례합니다.

닮지 않은 staging은 **가짜 통과 신호**를 줍니다. 세 가지가 특히 자주 걸립니다.

- **데이터 양이 다름** — N+1, 커넥션 풀 고갈, 인덱스 미사용은 행이 1,000개면 전부 통과합니다 (`day47-index-not-used.md`, `day17-why-index.md`)
- **권한이 다름** — staging IAM 역할이 넓으면 `AccessDenied`는 프로덕션에서만 납니다 (`day34-iam-least-privilege.md`)
- **외부 연동이 다름** — PG·푸시·메일이 샌드박스면, 실제 응답 코드와 지연은 프로덕션에서 처음 봅니다

"staging에서는 됐는데 프로덕션에서 안 되네"가 반복되면, staging을 더 고치는 게 답이 아닐 때가 많습니다. 먼저 할 일은 **무엇이 안 닮았는지 목록을 적는 것**입니다. 목록이 열 줄을 넘으면 그 staging은 검증 환경이 아니라 그냥 두 번째 dev입니다.

그리고 닮음을 유지할 예산이 없다면, staging을 줄이고 검증을 프로덕션 쪽으로 옮기는 게 정직한 선택입니다 — 카나리 배포, 피처 플래그, 섀도 트래픽. 최악은 **환경 셋을 다 유지하면서 아무것도 닮지 않은 상태**입니다. 비용은 셋을 내고 보증은 하나도 못 받습니다.

## 7. 함정

**프로필 주입 누락으로 dev 설정으로 프로덕션이 뜬다**
- **증상**: 배포는 성공, 헬스체크 통과, 트래픽도 정상. 그런데 데이터가 프로덕션 DB에 없습니다.
- **원인**: `application.yml`에 `spring.profiles.active` 기본값이 박혀 있고, 배포 환경변수가 그걸 덮지 못했습니다.
- **해법**: 기본 프로필을 없앱니다. 필수 설정에 기본값을 주지 않습니다. 활성 프로필을 기동 시점에 검증합니다(§5-1).

**프로덕션 데이터를 그대로 복제한 staging**
- **증상**: staging 테스트 중 실제 고객에게 주문 완료 메일과 푸시가 나갑니다.
- **원인**: 데이터 축의 격리를 포기하면 데이터뿐 아니라 **데이터에 붙은 식별자**(이메일, 전화번호, 결제 토큰)까지 넘어옵니다. 개인정보 처리 범위도 같이 넓어집니다.
- **해법**: 복제한다면 적재 파이프라인에서 식별자를 치환합니다. 치환이 어렵다면 복제 대신 합성 데이터를 쓰고, 양만 맞춥니다. 외부 발송 어댑터는 프로덕션 외 환경에서 기본적으로 차단되게 만듭니다.

**Terraform workspace로 환경을 나눴다**
- **증상**: dev `apply`가 프로덕션 리소스를 지우려고 계획에 올립니다. 혹은 dev 작업자가 프로덕션 state를 잠급니다.
- **원인**: workspace는 같은 backend·같은 자격증명을 공유합니다. `terraform workspace select`를 빠뜨리면 그대로 다른 환경에 적용됩니다.
- **해법**: 환경별 디렉터리 + 환경별 backend로 바꿉니다(§5-2). 환경별 state 버킷의 접근 권한도 환경별로 가릅니다.

**환경이 리소스를 공유한다**
- **증상**: 누군가 dev에서 Redis를 비운 뒤 프로덕션 캐시 히트율이 0으로 떨어집니다.
- **원인**: 키 접두사만 다른 같은 Redis 인스턴스, 혹은 경로만 다른 같은 S3 버킷. `FLUSHALL`과 버킷 수명주기 규칙은 접두사를 구분하지 않습니다.
- **해법**: 상태를 가진 리소스는 접두사로 나누지 않고 인스턴스를 나눕니다. 공유가 불가피하면(비용) 최소한 쓰기 권한을 환경별 자격증명으로 가릅니다.

**환경 이름이 애플리케이션 코드에 박힌다**
- **증상**: 새 환경(`perf`, `sandbox`)을 추가하려는데 `if ("prod".equals(env))`가 코드 전역에서 나옵니다. 하나 빠뜨리면 새 환경이 프로덕션처럼 동작합니다.
- **원인**: 환경 이름으로 분기하면 분기 지점이 환경 수 × 기능 수로 늘어납니다.
- **해법**: 환경 이름이 아니라 **기능 플래그**로 분기합니다. `if (notificationProperties.isExternalSendEnabled())`처럼 쓰고, 값은 환경별 설정에서 주입합니다. 코드는 환경이 몇 개인지 몰라야 합니다.

## 8. 결정 순서

새로 환경을 설계한다면 이 순서로 정합니다.

1. **아티팩트를 하나로 고정합니다.** 빌드는 한 번, 승격만 여러 번입니다.
2. **격리 강도를 정합니다.** 프로덕션과 나머지 사이는 최소 계정 분리, dev와 staging 사이는 VPC 또는 계정입니다.
3. **축별로 닮음과 격리를 표에 적습니다.** 적지 않으면 드리프트가 조용히 생깁니다(§3).
4. **데이터와 자격증명 격리를 먼저 막습니다.** 되돌릴 수 없는 사고는 거의 전부 이 두 축에서 납니다.
5. **staging에서 안 닮은 항목의 목록을 만듭니다.** 그 목록이 staging의 신뢰 범위입니다.
6. **환경 추가 비용을 재봅니다.** 환경 하나 늘릴 때 손으로 할 일이 있다면, 그 일은 언젠가 빠집니다.

## 9. 참고자료

- [12 Factor App — Dev/prod parity](https://12factor.net/dev-prod-parity)
- [AWS — 멀티 계정 사용의 이점](https://docs.aws.amazon.com/whitepapers/latest/organizing-your-aws-environment/benefits-of-using-multiple-aws-accounts.html)
- [AWS — 권장 OU와 계정](https://docs.aws.amazon.com/whitepapers/latest/organizing-your-aws-environment/recommended-ous-and-accounts.html)
- [AWS IAM — 크로스 계정 정책 평가 로직](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic-cross-account.html)
- [Spring Boot — Profiles](https://docs.spring.io/spring-boot/reference/features/profiles.html)
- [Terraform — Managing Workspaces](https://developer.hashicorp.com/terraform/cli/workspaces)
- 관련 문서: `day06-env-variable.md`, `day24-local-dev-env.md`, `day34-iam-least-privilege.md`, `day22-sg-vs-nacl.md`
