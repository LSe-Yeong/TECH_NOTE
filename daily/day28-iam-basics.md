# User, Role, Policy는 왜 셋으로 나뉘어 있는가 — IAM의 기본 구조

> 이 문서가 답할 질문: **IAM의 User·Role·Policy는 각각 무엇을 담당하고, 왜 하나로 합치지 않고 셋으로 나뉘어 있는가?**
>
> 기준: AWS IAM 사용자 가이드 (2026년 9월 확인). `day04-vpc-subnet.md`와 `day22-sg-vs-nacl.md`가 "네트워크 경계에서 패킷을 막는 법"이었다면, 이 문서는 **누가 무엇을 호출할 수 있는가를 정하는 경계**를 다룹니다.

## 1. 핵심 개념

IAM은 세 가지를 완전히 분리해서 관리합니다.

- **Policy** — 무엇을 할 수 있는지 적은 JSON 문서입니다. 그 자체로는 아무에게도 붙어 있지 않습니다.
- **User** — 사람 또는 워크로드 하나에 고정된 신원입니다. 비밀번호와 액세스 키 같은 **장기 자격증명**을 가집니다.
- **Role** — 권한 묶음이되 주인이 없습니다. 장기 자격증명이 없고, 필요할 때 누군가 **빌려 쓰면 임시 자격증명이 발급**됩니다.

> 이 분리를 이해하지 못하면 신입이 가장 먼저 저지르는 실수가 나옵니다. EC2에서 도는 애플리케이션이 S3를 읽어야 해서, 콘솔에서 IAM User를 만들고 액세스 키를 발급받아 `application.yml`이나 환경변수에 넣습니다. 잘 돕니다. 문제는 **그 키가 만료되지 않는다**는 점입니다. 저장소에 커밋되면 그 순간부터 유효하고, 퇴사한 사람 노트북에 남아 있어도 유효합니다. 유출을 알아채는 시점은 대체로 청구서를 볼 때입니다.
>
> Role은 정확히 이 문제를 없애려고 존재합니다. EC2에 Role을 붙이면 키를 아무 데도 저장하지 않고, 발급되는 자격증명은 몇 시간 뒤 자동으로 죽습니다.

즉 셋으로 나뉜 이유는 **"권한의 정의"·"신원"·"자격증명의 수명"을 각각 따로 바꾸기 위해서**입니다.

## 2. 구조

### 2-1. Policy — 권한을 적는 문서

정책은 `Statement` 배열이고, 문장 하나가 다음 요소로 구성됩니다.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadOrderReceipts",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::order-receipts-prod",
        "arn:aws:s3:::order-receipts-prod/*"
      ],
      "Condition": {
        "Bool": { "aws:SecureTransport": "true" }
      }
    }
  ]
}
```

- `Effect` — `Allow` 또는 `Deny`
- `Action` — `s3:GetObject`처럼 `서비스:오퍼레이션` 형태
- `Resource` — 대상의 ARN. 서비스마다 지원 범위가 다르고, `*`만 받는 액션도 있습니다
- `Condition` — 요청 컨텍스트(IP, TLS 여부, 시각, 태그)로 거는 추가 조건

`Version`은 날짜가 아니라 **정책 언어의 버전 식별자**입니다. `2012-10-17`이 현행이고, 이걸 빼면 변수 치환 같은 기능이 동작하지 않습니다.

정책은 붙이는 방식에 따라 두 종류입니다.

| | 관리형 정책(Managed) | 인라인 정책(Inline) |
|---|---|---|
| 재사용 | 여러 신원에 붙임 | 한 신원에만 종속 |
| 버전 | 버전 관리·롤백 가능 | 없음 |
| 크기 상한 | 고객 관리형 6,144자 | 사용자 2,048 / 역할 10,240 / 그룹 5,120자 |
| 신원당 연결 수 | 역할 20개(최대 25), 사용자 10개(최대 20) | 개수 제한 없음(합산 크기만) |

크기 계산에서 공백은 세지 않습니다. 기본은 관리형이고, 인라인은 "이 역할에서만 의미가 있어서 딴 데 붙으면 위험한 권한"에 씁니다. ([IAM 쿼터](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_iam-quotas.html))

### 2-2. User와 Group — 신원과 묶음

User는 계정 안에서 이름이 유일하고(대소문자 구분 없음), 사람이면 콘솔 비밀번호, 프로그램이면 액세스 키를 가집니다. Group은 권한을 붙이기 위한 묶음일 뿐이라 **Group 자체는 로그인할 수 없고 자격증명도 없습니다.** 그룹을 그룹 안에 넣는 것도 안 됩니다.

AWS가 명시적으로 IAM User가 필요하다고 인정하는 경우는 좁습니다. 역할을 쓸 수 없는 워크로드, IAM Identity Center를 지원하지 않는 서드파티 클라이언트, 그리고 **IdP가 죽었을 때 쓸 비상 접근 사용자**입니다. 사람이 콘솔에 들어가려고 User를 만드는 건 이 목록에 없습니다. ([IAM 역할 문서](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles.html))

### 2-3. Role — 정책 두 장으로 이루어진 신원

Role은 정책을 **두 장** 가집니다. 여기가 User와 결정적으로 다른 지점입니다.

- **신뢰 정책(Trust policy)** — 누가 이 역할을 빌릴 수 있는가. 역할에 붙는 리소스 기반 정책이며 필수입니다.
- **권한 정책(Permissions policy)** — 빌린 사람이 무엇을 할 수 있는가.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "ec2.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

이 두 장이 나뉘어 있어서 **"권한을 늘리는 일"과 "그 권한을 쓸 사람을 늘리는 일"이 분리**됩니다. 다른 계정에 접근을 열어줄 때도, 리소스를 가진 쪽이 신뢰 정책에 상대 계정을 적고 상대 쪽은 `sts:AssumeRole`을 허용하는 식으로 양쪽이 모두 동의해야 성립합니다. 한쪽만으로는 절대 뚫리지 않습니다.

역할을 빌리면 STS가 임시 자격증명(액세스 키 ID + 시크릿 + **세션 토큰**)을 돌려줍니다. 세션 토큰이 함께 오는 것이 장기 키와의 눈에 보이는 차이입니다.

| 항목 | 값 |
|---|---|
| `DurationSeconds` 지정 범위 | 900초(15분) ~ 역할의 최대 세션 설정(1~12시간) |
| 미지정 시 | 1시간 |
| 역할 체이닝(역할로 역할 빌리기) | 최대 1시간. 개별 역할 설정과 무관 |
| STS 요청 쿼터 | 계정·리전당 기본 600 req/s |

([IAM 쿼터](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_iam-quotas.html))

## 3. 흐름

### 3-1. 요청 하나가 허가되는 순서

`GetObject` 호출 한 번이 통과하기까지의 판정 순서입니다.

1. **인증** — 서명된 자격증명이 어느 주체(Principal)인지 확인합니다.
2. **요청 컨텍스트 수집** — 액션, 리소스, 주체, 환경 데이터(IP·시각·TLS), 리소스 데이터(태그 등)를 모읍니다.
3. **적용될 정책 수집** — 자격 증명 기반 정책, 리소스 기반 정책, 권한 경계, SCP/RCP, 세션 정책.
4. **판정.**

판정 규칙 네 줄이 IAM의 전부입니다.

```text
기본값은 거부(암묵적 거부)
 → 어느 정책이든 명시적 Allow가 있으면 허용으로 뒤집힘
 → 단, SCP·RCP·권한 경계·세션 정책이 존재하면 그것들도 전부 Allow여야 함(교집합)
 → 어느 정책에든 명시적 Deny가 하나라도 있으면 무조건 거부(최우선)
```

여기서 실무 판단이 갈립니다. **자격 증명 기반 정책과 리소스 기반 정책은 합집합**입니다. 둘 중 하나만 허용해도 통과합니다. 반면 **권한 경계, SCP, 세션 정책은 교집합**입니다. 이쪽은 권한을 주는 장치가 아니라 상한을 정하는 장치라, 아무리 많이 붙여도 권한이 늘지 않습니다. ([정책 평가 로직](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic.html))

### 3-2. EC2 위의 코드는 어떻게 자격증명을 얻는가

역할이 실제로 작동하는 경로입니다.

```text
Role(신뢰 정책: ec2.amazonaws.com)
  → 인스턴스 프로파일에 담김
  → EC2 인스턴스에 연결
  → 인스턴스 메타데이터 서비스(IMDS)가 임시 자격증명을 노출
  → SDK의 기본 자격증명 공급자 체인이 그걸 찾아 씀
  → 만료 전에 SDK가 알아서 갱신
```

SDK는 자격증명을 **여러 위치에서 순서대로 찾다가 처음 유효한 것을 만나면 멈춥니다.** 흔히 포함되는 위치는 정적 액세스 키(환경변수·공유 파일), IAM Identity Center, assume-role 설정, 컨테이너 자격증명(ECS/EKS), 그리고 마지막에 IMDS입니다. 정확한 순서는 SDK마다 다르므로 쓰는 SDK 문서를 봐야 합니다. ([표준 자격증명 공급자](https://docs.aws.amazon.com/sdkref/latest/guide/standardized-credentials.html))

이 "먼저 찾은 게 이긴다"가 실무 디버깅의 절반입니다. 로컬에 남아 있던 `AWS_ACCESS_KEY_ID` 환경변수 하나 때문에, 역할을 제대로 붙인 컨테이너가 엉뚱한 신원으로 도는 일이 계속 생깁니다.

## 4. 예제

### 4-1. 이렇게 하면 안 됩니다 ❌

```java
// ❌ 액세스 키를 코드/설정에 박아 넣는 방식
AwsBasicCredentials credentials = AwsBasicCredentials.create(
        System.getenv("APP_AWS_ACCESS_KEY"),      // 만료되지 않는 장기 키
        System.getenv("APP_AWS_SECRET_KEY"));

S3Client s3 = S3Client.builder()
        .region(Region.AP_NORTHEAST_2)
        .credentialsProvider(StaticCredentialsProvider.create(credentials))
        .build();
```

문제는 유출 위험만이 아닙니다. 이 코드는 **회전(rotation)이 불가능**합니다. 키를 바꾸려면 배포를 해야 하고, 그래서 아무도 안 바꿉니다.

### 4-2. 개선한 코드 ✔️

```java
// ✔️ 자격증명을 코드에서 아예 다루지 않습니다
S3Client s3 = S3Client.builder()
        .region(Region.AP_NORTHEAST_2)
        .credentialsProvider(DefaultCredentialsProvider.create())
        .build();
```

로컬에서는 개발자의 SSO 세션을, EC2/ECS/EKS에서는 붙어 있는 역할을 자동으로 씁니다. **환경마다 코드가 같고 신원만 달라집니다.** 잘 돌아가는지 확인하는 가장 빠른 방법은 지금 무슨 신원인지 물어보는 것입니다.

```bash
aws sts get-caller-identity
# {
#   "UserId": "AROAEXAMPLEID:i-0123456789abcdef0",
#   "Account": "111122223333",
#   "Arn": "arn:aws:sts::111122223333:assumed-role/order-api-role/i-0123456789abcdef0"
# }
```

`assumed-role`이 보이면 역할로 도는 것이고, `arn:aws:iam::...:user/...`가 보이면 어딘가의 장기 키를 쓰고 있는 것입니다.

## 5. 권한을 주는 정책과 상한을 정하는 정책

3-1에서 "교집합으로 평가되는 정책"이 따로 있다고 했습니다. 여기가 IAM에서 가장 늦게 이해되는 부분이고, 조직이 커지면 반드시 만나는 지점입니다.

문제는 이렇게 생깁니다. 개발자가 Lambda나 ECS 작업을 만들려면 역할이 필요한데, 매번 플랫폼 팀에 요청하면 병목이 됩니다. 그렇다고 `iam:CreateRole`과 `iam:AttachRolePolicy`를 그냥 주면 **누구나 `AdministratorAccess`를 붙인 역할을 만들어 빌릴 수 있습니다.** 권한을 만들 권한은 곧 모든 권한입니다.

**권한 경계(Permissions Boundary)** 가 이걸 푸는 장치입니다. 관리형 정책을 신원에 "상한"으로 붙이면, 실제 권한은 `자격 증명 기반 정책 ∩ 권한 경계`가 됩니다. 경계 자체는 아무 권한도 주지 않습니다.

핵심은 위임할 때 **경계를 붙이도록 강제하는 것**입니다.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CreateRoleOnlyWithBoundary",
      "Effect": "Allow",
      "Action": ["iam:CreateRole", "iam:AttachRolePolicy", "iam:PutRolePolicy"],
      "Resource": "arn:aws:iam::111122223333:role/app-*",
      "Condition": {
        "StringEquals": {
          "iam:PermissionsBoundary":
            "arn:aws:iam::111122223333:policy/DeveloperBoundary"
        }
      }
    },
    {
      "Sid": "NoBoundaryPolicyEdit",
      "Effect": "Deny",
      "Action": [
        "iam:CreatePolicyVersion",
        "iam:DeletePolicy",
        "iam:DeletePolicyVersion",
        "iam:SetDefaultPolicyVersion"
      ],
      "Resource": "arn:aws:iam::111122223333:policy/DeveloperBoundary"
    },
    {
      "Sid": "NoBoundaryDetach",
      "Effect": "Deny",
      "Action": "iam:DeleteRolePermissionsBoundary",
      "Resource": "*"
    }
  ]
}
```

뒤의 두 문장이 없으면 첫 번째 문장은 무의미합니다. 경계 정책의 **내용을 고치거나**(새 버전을 만들어 기본 버전으로 지정) 경계를 **떼어낼 수** 있으면 상한이 상한이 아닙니다. 두 가지는 대상이 다릅니다. 내용 수정은 정책 ARN에 대한 액션이고, 떼어내기는 역할에 대한 액션이라 `Resource`가 정책 ARN이 아닙니다. 이걸 한 문장에 몰아넣으면 아무것도 막지 못합니다. **명시적 Deny가 모든 Allow를 이긴다**는 규칙을 여기서 실제로 써먹습니다.

상한을 정하는 장치는 적용 범위가 서로 다릅니다.

| 장치 | 적용 대상 | 붙이는 위치 | 권한을 주는가 |
|---|---|---|---|
| 권한 경계 | 특정 User·Role 하나 | 그 신원 | 아니요 |
| SCP | 계정 안의 모든 주체 | 조직/OU/계정 | 아니요 |
| RCP | 계정 안의 리소스 | 조직/OU/계정 | 아니요 |
| 세션 정책 | 그 세션 하나 | `AssumeRole` 호출 시 | 아니요 |

넷 다 "권한을 부여하지 않는다"는 점이 같습니다. SCP를 붙였는데 아무도 아무것도 못 하게 됐다면 십중팔구 이걸 권한 부여 도구로 착각한 것입니다. 실제 권한은 언제나 자격 증명 기반 정책이나 리소스 기반 정책이 줍니다.

한 가지 반직관적인 예외가 있습니다. **권한 경계의 암묵적 거부는 리소스 기반 정책을 막지 못합니다.** 경계에 Secrets Manager가 아예 없어서 그쪽 권한이 하나도 없는 역할이라도, 시크릿에 붙은 리소스 기반 정책이 그 역할에게 `secretsmanager:GetSecretValue`를 허용하면 값을 읽습니다. 정말로 막으려면 경계에 **명시적 Deny**를 적어야 합니다. "경계에 안 적었으니 못 하겠지"는 리소스 기반 정책 앞에서 성립하지 않습니다. ([권한 경계](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_boundaries.html))

세션 정책은 잘 안 쓰이지만 쓸모가 분명합니다. 하나의 역할을 여러 테넌트가 공유할 때, `AssumeRole` 시점에 "이 세션은 이 접두사 아래 객체만"이라고 좁혀서 발급할 수 있습니다. 다만 전달하는 JSON 정책과 관리형 정책 ARN을 합쳐 2,048자, 관리형 정책 ARN은 최대 10개라는 제약이 있습니다.

## 6. 함정

### 6-1. 권한을 고쳤는데 여전히 AccessDenied가 납니다

- **증상**: 정책에 액션을 추가하고 저장했는데 몇 초~몇십 초 동안 계속 거부됩니다. Terraform으로 역할을 만들고 곧바로 그 역할을 쓰는 리소스를 만들면 간헐적으로 실패합니다.
- **원인**: IAM은 분산 구조라 **최종적 일관성(eventual consistency)** 을 가집니다. 변경이 모든 엔드포인트에 보이기까지 시간이 걸리고 캐시도 끼어 있습니다.
- **해법**: IAM 변경은 애플리케이션 실행 경로가 아니라 **별도의 초기화·셋업 단계**에 두고, 의존하는 작업 전에 전파를 확인합니다. 실패 시 재시도를 넣습니다. ([IAM 문제 해결](https://docs.aws.amazon.com/IAM/latest/UserGuide/troubleshoot.html))

### 6-2. `iam:PassRole`을 넓게 준 순간 관리자 권한이 새어나갑니다

- **증상**: 개발자에게 Lambda 생성 권한만 줬는데, 그 사람이 사실상 계정 전체를 조작할 수 있습니다.
- **원인**: 서비스에 역할을 넘기려면 `iam:PassRole`이 필요한데, 이걸 `"Resource": "*"`로 주면 **자기보다 강한 역할을 골라서 서비스에 넘길 수 있습니다.** S3 권한이 전혀 없는 사람도, S3 전권을 가진 역할을 붙인 Lambda를 만들어 대신 실행시키면 됩니다. 더 나쁜 건 `PassRole`이 API 호출이 아니라 권한이라 **CloudTrail에 `PassRole` 기록이 남지 않는다**는 점입니다. 역할이 넘어간 사실은 `CreateFunction` 같은 리소스 생성 로그를 봐야 알 수 있습니다.
- **해법**: `Resource`를 접두사로 좁히고(`arn:aws:iam::111122223333:role/app-lambda-*`), `iam:PassedToService` 조건 키로 넘길 수 있는 서비스까지 못 박습니다. ([PassRole 문서](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_passrole.html))

### 6-3. 신뢰 정책의 Principal에 와일드카드를 쓰려다 막힙니다

- **증상**: 신뢰 정책의 `Principal`에 `arn:aws:iam::111122223333:role/deploy-*`처럼 적었더니 저장이 되지 않습니다.
- **원인**: 신뢰 정책의 `Principal` 요소에서는 **ARN의 일부로 `*`를 쓸 수 없습니다.**
- **해법**: `Principal`에는 계정 루트(`arn:aws:iam::111122223333:root`)를 적어 계정 단위로 열고, 실제 좁히기는 `Condition`(`aws:PrincipalArn` 등)과 상대 계정 쪽 정책에서 합니다. 다만 계정 루트를 적는다는 건 "저 계정에서 `sts:AssumeRole` 권한을 받은 누구든"이라는 뜻이므로, 조건 없이 방치하면 안 됩니다.

### 6-4. 콘솔에서 역할을 전환했더니 12시간이 아니라 1시간 만에 끊깁니다

- **증상**: 역할의 최대 세션 시간을 12시간으로 올렸는데도 세션이 1시간 만에 만료됩니다.
- **원인**: 두 가지 중 하나입니다. **(1)** 역할로 역할을 빌리는 역할 체이닝이면 개별 설정과 무관하게 **최대 1시간**으로 잘립니다. **(2)** `DurationSeconds`를 지정하지 않으면 기본값이 1시간입니다.
- **해법**: 체이닝 단계를 줄이거나, CLI/SDK에서 `--duration-seconds`를 명시합니다. 콘솔에서 전환한 경우 최대 세션 시간과 원래 사용자 세션의 남은 시간 중 **짧은 쪽**이 적용됩니다.

### 6-5. 관리형 정책을 계속 붙이다가 한도에 걸립니다

- **증상**: 역할에 정책을 붙이려는데 `LimitExceeded`가 납니다.
- **원인**: 역할당 관리형 정책은 기본 20개(상향 최대 25개)입니다. 서비스가 늘 때마다 정책을 하나씩 추가하는 습관이면 금방 찹니다.
- **해법**: 한도를 올리기 전에 정책을 **역할의 목적 단위로 통합**합니다. 정책 개수가 20개라는 건 대개 그 역할이 하는 일이 20가지라는 뜻이고, 역할을 쪼개야 한다는 신호입니다.

## 7. 정리하면

- **Policy는 권한의 정의, User는 신원, Role은 임시로 빌려 쓰는 권한 묶음**입니다. 셋을 나눈 이유는 자격증명의 수명을 권한 정의와 분리하기 위해서입니다.
- **판정은 "기본 거부 → 명시적 Allow로 뒤집기 → 상한 정책들과 교집합 → 명시적 Deny가 최우선"** 네 줄입니다.
- 사람이든 워크로드든 **기본 선택은 Role**입니다. IAM User는 역할을 못 쓰는 예외 상황과 비상 접근용입니다.
- 권한을 늘리는 것보다 **`iam:PassRole`처럼 권한을 넘기는 권한**이 훨씬 위험합니다.

<!-- TODO: 확인 필요 — 신뢰 정책 Principal에 계정 루트를 적었을 때 `aws:PrincipalArn` 조건으로 좁히는 패턴은 널리 쓰이지만, 조건 키 조합에 따라 의도치 않게 넓어지는 경우가 있어 실제 계정에서 IAM Access Analyzer로 검증한 결과까지는 확인하지 못했습니다. -->

## 8. 참고자료

- [How IAM works — AWS IAM User Guide](https://docs.aws.amazon.com/IAM/latest/UserGuide/intro-structure.html)
- [Policy evaluation logic](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_evaluation-logic.html)
- [IAM roles](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles.html)
- [Security best practices in IAM](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
- [Permissions boundaries for IAM entities](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_boundaries.html)
- [IAM and AWS STS quotas](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_iam-quotas.html)
- [Grant a user permissions to pass a role to an AWS service](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_passrole.html)
- 관련 문서: `day06-env-variable.md` (설정과 시크릿의 경계), `day22-sg-vs-nacl.md` (네트워크 경계의 허용·거부)
