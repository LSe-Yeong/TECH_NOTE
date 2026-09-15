# 최소 권한은 왜 실무에서 무너지는가

> 이 문서가 답할 질문: **모두가 최소 권한을 알고 있는데 계정은 왜 항상 과잉 권한 상태인가. 정확히 어디서 무너지고, 무엇으로 되돌리는가?**
>
> 기준: AWS IAM 사용자 가이드 · IAM Access Analyzer (2026년 9월 확인). `day28-iam-basics.md`에서 User·Role·Policy의 구조와 판정 순서를 다뤘습니다. 이 문서는 그 위에서 **권한의 범위를 어떻게 줄여나가는가**만 다룹니다.

## 1. 최소 권한은 상태가 아니라 과정입니다

최소 권한(least privilege)은 **작업에 필요한 권한만 주는 것**입니다. 정책에서 좁힐 수 있는 축은 세 개뿐입니다.

- **Action** — 무슨 API를 부를 수 있는가
- **Resource** — 어떤 대상에
- **Condition** — 어떤 상황에서만

셋 다 `*`인 정책이 `AdministratorAccess`이고, 셋을 차례로 좁히는 일이 최소 권한 작업의 전부입니다.

> 문제는 이 작업이 **한 번 하고 끝나는 일이 아니라는 점**입니다. 실무에서 권한은 항상 이 순서로 움직입니다. 배포가 급해서 `s3:*`로 열고 → 돌아가니까 넘어가고 → 6개월 뒤 아무도 그 역할이 왜 그 권한을 가졌는지 모릅니다. 권한을 **넓히는 일에는 "안 돌아간다"는 강력한 압력**이 있지만, **좁히는 일에는 아무 압력도 없습니다.** 그래서 권한은 단방향으로만 자랍니다.
>
> 그 결과가 드러나는 시점은 정해져 있습니다. 액세스 키 하나가 저장소에 올라가거나 로그에 찍혔을 때, 그 키로 할 수 있는 일의 범위가 곧 사고의 크기가 됩니다. `s3:GetObject` 하나만 있는 키와 `s3:*`인 키는 유출 확률은 같고 피해는 완전히 다릅니다.

AWS 문서도 "처음에는 넓게 시작하고, 유스케이스가 자리잡으면 줄여나가라"고 말합니다. 즉 **넓게 시작하는 것 자체는 틀리지 않았습니다.** 틀리는 건 줄이는 단계가 실제로 실행되지 않는다는 점입니다. 그래서 이 문서는 "좁혀 쓰세요"가 아니라 **좁히는 작업을 어떻게 강제로 일어나게 만드는가**를 다룹니다.

## 2. 무너지는 지점 다섯 군데

### 2-1. 시작할 때 필요한 권한을 모릅니다

- **증상**: 새 서비스를 붙일 때 정확히 어떤 액션이 필요한지 알 수 없습니다. 문서를 뒤져 정책을 짜면 배포 후 `AccessDenied`가 나고, 고치고 재배포하고를 반복합니다. 결국 `"Action": "s3:*"`로 열고 넘어갑니다.
- **원인**: 하나의 SDK 호출이 여러 API를 부릅니다. `s3:PutObject`만 있으면 될 것 같은 업로드가 멀티파트로 전환되면 `s3:CreateMultipartUpload`·`s3:UploadPart`·`s3:AbortMultipartUpload`를 요구합니다. 필요한 액션 목록은 **코드를 읽어서 알아내는 게 아니라 실행해봐야 알 수 있습니다.**
- **해법**: 추측하지 말고 **실행 기록에서 뽑습니다.** IAM Access Analyzer의 정책 생성이 이 일을 합니다(3-1).

### 2-2. 좁히는 순간이 무섭습니다

- **증상**: 권한을 줄이자는 말은 나오는데 아무도 손대지 않습니다. "이거 빼도 되나요?"에 자신 있게 답할 사람이 없습니다.
- **원인**: **한 달에 한 번 도는 정산 배치**가 있기 때문입니다. 지난 7일 로그만 보고 권한을 빼면 월말에 터집니다. 권한 축소는 실패가 즉시 드러나지 않고, 한참 뒤에 엉뚱한 곳에서 드러납니다.
- **해법**: 관측 기간을 **업무 주기보다 길게** 잡습니다. IAM의 last accessed 정보는 서비스 수준으로 최소 400일치를 보관합니다. ([last accessed 정보](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_last-accessed.html)) 다만 **액션 수준**은 추적 시작일이 서비스마다 다릅니다. S3 관리 액션은 2020년 4월 12일, EC2·IAM·Lambda는 2021년 4월 7일, **그 외 전 서비스는 2023년 5월 23일**부터입니다. 그 전 기록은 없는 게 아니라 **애초에 수집되지 않았습니다.**

### 2-3. 와일드카드는 시간이 지나면서 저절로 자랍니다

- **증상**: 정책을 고친 적이 없는데 역할의 권한이 늘어 있습니다.
- **원인**: 두 가지입니다. **(1)** `s3:*`나 `iam:Get*` 같은 와일드카드는 AWS가 새 액션을 추가하면 **자동으로 그 액션까지 포함합니다.** 저장소의 정책 파일은 한 글자도 안 바뀌므로 diff에 잡히지 않습니다. **(2)** AWS 관리형 정책은 AWS가 내용을 갱신하고, 갱신은 **그 정책이 붙은 모든 신원에 즉시 반영됩니다.** `ReadOnlyAccess`는 새 서비스가 출시될 때마다 그 서비스의 읽기 권한이 추가됩니다. ([관리형 정책과 인라인 정책](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_managed-vs-inline.html))
- **해법**: AWS 관리형 정책은 **출발점으로만** 씁니다. 실제로 쓰는 액션이 확정되면 고객 관리형 정책으로 옮깁니다. 와일드카드를 남겨야 한다면 최소한 `Resource`나 `Condition` 중 하나는 반드시 좁혀둡니다.

### 2-4. 위험한 건 권한이 아니라 "권한을 만드는 권한"입니다

- **증상**: 개발자에게 Lambda 배포 권한만 줬는데 사실상 계정 관리자가 됩니다.
- **원인**: 몇몇 액션은 **자기보다 강한 신원을 얻는 경로**를 엽니다. `iam:PassRole`을 `Resource: "*"`로 주면 강한 역할을 골라 서비스에 넘길 수 있고, `lambda:UpdateFunctionCode`는 강한 역할로 도는 함수의 코드를 바꿔 그 자격증명을 꺼낼 수 있고, `iam:CreatePolicyVersion`은 이미 붙어 있는 정책의 새 버전을 만들어 기본 버전으로 지정할 수 있습니다. **액션 개수를 세면 이 셋은 "권한 3개"지만 실제 효과는 `AdministratorAccess`입니다.**
- **해법**: 권한 검토를 "몇 개 줬나"가 아니라 **"여기서 더 강해질 수 있나"** 기준으로 합니다. `iam:PassRole`은 `Resource`를 접두사로 좁히고 `iam:PassedToService` 조건을 겁니다(`day28-iam-basics.md` 6-2). 정책 편집 액션은 권한 경계 정책에 대해 명시적 `Deny`로 못 박습니다.

### 2-5. 임시 권한은 영구가 됩니다

- **증상**: 장애 대응하느라 붙인 관리자 정책이 1년째 붙어 있습니다.
- **원인**: 붙이는 행위에는 담당자와 시점이 있지만 **떼는 행위에는 담당자도 시점도 없습니다.** 되돌리는 일을 기억에 맡기면 되돌아가지 않습니다.
- **해법**: 임시 권한은 **만료가 내장된 수단**으로만 줍니다. 역할을 하나 더 만들고 세션으로 빌려 쓰게 하면 시간이 지나 저절로 사라집니다. 정책을 직접 붙여야 한다면 `aws:CurrentTime` 조건으로 기한을 정책 안에 적습니다. 어느 쪽이든 **해제를 사람의 할 일 목록에서 빼는 것**이 핵심입니다.

## 3. 좁히는 절차 — Action → Resource → Condition

한꺼번에 좁히면 뭐가 깨졌는지 모릅니다. 순서대로 합니다.

### 3-1. Action: 실행 기록에서 뽑습니다

IAM Access Analyzer는 CloudTrail 기록을 읽어 그 역할이 **실제로 쓴 액션**으로 정책을 만들어줍니다.

```bash
aws accessanalyzer start-policy-generation \
  --policy-generation-details '{"principalArn":"arn:aws:iam::111122223333:role/order-api-role"}' \
  --cloud-trail-details file://trail-details.json

# 잠시 뒤 결과 조회
aws accessanalyzer get-generated-policy --job-id "<job-id>"
```

쓰기 전에 알아야 할 제약이 있습니다. ([정책 생성](https://docs.aws.amazon.com/IAM/latest/UserGuide/access-analyzer-policy-generation.html))

| 항목 | 내용 |
|---|---|
| 분석 기간 | 최대 90일. 길수록 생성이 느립니다 |
| 전제 | 계정에 CloudTrail 추적이 켜져 있어야 합니다 |
| 데이터 이벤트 | **분석하지 않습니다.** S3 오브젝트 읽기·쓰기는 안 잡힙니다 |
| `iam:PassRole` | CloudTrail이 추적하지 않아 **생성된 정책에 포함되지 않습니다** |
| 콘솔 보관 | 생성 후 7일. 계정당 한 번에 하나만 |

이 표의 3·4행이 결정적입니다. 생성된 정책을 그대로 붙이면 **S3 오브젝트 접근과 `PassRole`이 통째로 빠진 채 배포됩니다.** 생성 결과는 초안이지 완성품이 아닙니다.

또 하나. 정책 생성은 **거부된 호출까지 포함해서** 분석합니다. 누가 실수로 부른 액션이 그대로 정책에 들어올 수 있으니 목록을 눈으로 훑어야 합니다.

### 3-2. Resource: ARN으로 좁히되, 안 되는 액션이 있습니다

액션이 정해지면 대상을 좁힙니다. 이때 **모든 액션이 리소스 수준 권한을 지원하지는 않습니다.** `ec2:DescribeInstances`처럼 대상 지정이 불가능해 `"Resource": "*"`만 받는 액션이 있습니다. 어떤 액션이 무엇을 지원하는지는 [Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/reference_policies_actions-resources-contextkeys.html)에서 서비스별로 확인합니다.

`*`를 강제당하는 액션은 **Condition으로 좁혀야 합니다.** 여기서 3-3으로 넘어갑니다.

### 3-3. Condition: 가장 효율이 좋고, 가장 조용히 망가집니다

조건은 액션·리소스를 건드리지 않고 범위를 크게 줄입니다. 자주 쓰는 것들입니다.

- `aws:PrincipalOrgID` — 우리 조직 소속 주체만. 리소스 기반 정책에서 특히 강력합니다
- `aws:RequestedRegion` — 쓰는 리전 밖의 호출 차단
- `aws:ResourceTag/<키>` — 태그 기반 접근 제어(ABAC)
- `aws:SecureTransport` — TLS 아닌 요청 차단

문제는 **조건 키가 요청 컨텍스트에 없을 때**입니다. 단일 값 키가 없으면 조건은 참이 되지 못하고, 그 문장은 적용되지 않아 결과적으로 거부됩니다. 대표적인 사례가 `aws:SourceIp`입니다. **요청이 VPC 엔드포인트를 지나면 이 키가 아예 포함되지 않습니다.** ([전역 조건 키](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_condition-keys.html))

```json
{
  "Sid": "AllowFromOfficeOrVpc",
  "Effect": "Allow",
  "Action": "s3:GetObject",
  "Resource": "arn:aws:s3:::order-receipts-prod/*",
  "Condition": {
    "IpAddressIfExists": { "aws:SourceIp": ["192.0.2.0/24"] },
    "StringEqualsIfExists": { "aws:SourceVpce": ["vpce-0abc123example"] }
  }
}
```

`IfExists`는 **"키가 있으면 검사하고, 없으면 통과"** 입니다. 사무실 IP에서 오면 IP를 보고, VPC 엔드포인트를 지나오면 엔드포인트 ID를 봅니다. 다만 이건 양날입니다. 조건을 **차단 목적**으로 쓸 때 `IfExists`를 붙이면 키가 없는 요청이 전부 빠져나갑니다. 차단은 `IfExists` 없이 `Deny`로 쓰는 게 맞습니다.

## 4. 정책 하나를 좁혀보기

주문 영수증을 S3에 올리고 내려받는 서비스의 역할입니다.

### 4-1. 흔히 나오는 정책 ❌

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "s3:*",
      "Resource": "*"
    }
  ]
}
```

이 정책의 진짜 문제는 "권한이 많다"가 아닙니다. **`s3:DeleteBucket`과 `s3:PutBucketPolicy`가 들어 있다는 점**입니다. 애플리케이션 버그 하나로 버킷 정책이 바뀌어 공개 버킷이 될 수 있고, 계정 안의 **다른 모든 버킷**까지 범위에 들어옵니다.

### 4-2. 세 축을 모두 좁힌 정책 ✔️

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListOnlyOrderPrefix",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::order-receipts-prod",
      "Condition": {
        "StringLike": { "s3:prefix": ["receipts/*"] }
      }
    },
    {
      "Sid": "ReadWriteReceiptObjects",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:AbortMultipartUpload"
      ],
      "Resource": "arn:aws:s3:::order-receipts-prod/receipts/*",
      "Condition": {
        "Bool": { "aws:SecureTransport": "true" },
        "StringEquals": { "aws:RequestedRegion": "ap-northeast-2" }
      }
    }
  ]
}
```

세 가지가 달라졌습니다.

1. **액션** — 삭제와 버킷 설정 변경이 사라졌습니다. 영수증은 지울 일이 없습니다.
2. **리소스** — 버킷 하나, 그 안의 접두사 하나. `ListBucket`은 버킷 ARN에, 오브젝트 액션은 `/receipts/*`에 걸립니다. **이 둘의 ARN 모양이 다르다는 점**이 S3 정책에서 가장 자주 틀리는 부분입니다.
3. **조건** — TLS 강제, 리전 고정.

## 5. 좁힌 상태를 유지하는 장치

한 번 좁혀도 2-3처럼 다시 자랍니다. 되돌아가는 걸 막는 장치는 두 종류이고, 둘 다 유료입니다.

### 5-1. 배포 전: 커스텀 정책 검사

정책 변경이 **권한을 넓히는 변경인지**를 CI에서 판정합니다.

```bash
# 기존 정책 대비 새 권한이 생기는지 검사
aws accessanalyzer check-no-new-access \
  --existing-policy-document file://policy-current.json \
  --new-policy-document file://policy-new.json \
  --policy-type IDENTITY_POLICY

# 절대 허용하면 안 되는 액션이 들어왔는지 검사
aws accessanalyzer check-access-not-granted \
  --policy-document file://policy-new.json \
  --access '[{"actions":["iam:CreatePolicyVersion","iam:PassRole"]}]' \
  --policy-type IDENTITY_POLICY
```

`check-no-new-access`는 리뷰어가 눈으로 못 잡는 걸 잡습니다. 와일드카드 한 글자 차이로 권한이 넓어지는 변경을 자동 추론으로 판정하기 때문입니다. 요금은 **API 호출 1건당 $0.0020**입니다. ([Access Analyzer 요금](https://aws.amazon.com/iam/access-analyzer/pricing/))

무료로 쓸 수 있는 정책 검증(policy validation)도 별개로 있습니다. 100가지가 넘는 검사로 문법과 위험 패턴을 짚어줍니다. ([IAM 보안 모범 사례](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html))

### 5-2. 배포 후: 미사용 접근 분석기

붙어 있지만 안 쓰는 권한·역할·키를 계속 찾아냅니다. 찾는 대상은 네 가지입니다. **미사용 역할**, **미사용 액세스 키**, **미사용 콘솔 비밀번호**, 그리고 **역할이 안 쓰는 권한**입니다.

| 항목 | 값 |
|---|---|
| 추적 기간 | 1~365일 사이로 지정 |
| 분석 대상 | **추적 기간 전체를 존재한** 엔티티만 |
| 요금 | 분석기당 IAM 역할·사용자 1개당 월 $0.20 |
| 외부 접근 분석기 | 무료 (별도 기능) |

([미사용 접근 분석기 생성](https://docs.aws.amazon.com/IAM/latest/UserGuide/access-analyzer-create-unused.html), [Access Analyzer 요금](https://aws.amazon.com/iam/access-analyzer/pricing/))

2행이 중요합니다. 추적 기간을 90일로 잡으면 **90일보다 최근에 만들어진 역할은 아예 분석되지 않습니다.** "새로 만든 역할이 목록에 안 보이는데요"의 답이 이것입니다.

요금은 역할 수에 비례하므로, 태그로 제외 규칙을 걸거나 조직 단위로 분석기를 하나만 두는 식으로 조절합니다.

## 6. 함정

### 6-1. last accessed가 "미사용"이라는데 빼면 터집니다

- **증상**: 서비스 last accessed에 기록이 없어 권한을 뺐는데 장애가 납니다.
- **원인**: last accessed는 **자격 증명 기반 정책만** 봅니다. 리소스 기반 정책, SCP, 권한 경계, 세션 정책으로 이뤄진 접근은 리포트에 잡히지 않습니다. 또 액션 수준 정보는 **관리 이벤트만** 대상이라 데이터 플레인 호출은 들어오지 않습니다.
- **해법**: 권한 회수 판단은 last accessed 단독으로 하지 않습니다. 판정의 최종 근거는 CloudTrail입니다. AWS도 리포트가 아니라 CloudTrail을 권위 있는 출처로 명시합니다.

### 6-2. 콘솔 리포트가 비어 있습니다

- **증상**: 방금 호출했는데 last accessed 표가 비어 있거나 반영되지 않습니다.
- **원인**: 최근 활동이 콘솔에 나타나기까지 **최대 4시간**이 걸립니다. 게다가 리포트는 **생성한 주체만** 볼 수 있어서, 임시 자격증명으로 만들었다면 같은 세션 안에서 조회해야 합니다.
- **해법**: 4시간을 기다리고, CLI/API로는 리포트를 새로 생성해서 받습니다.

### 6-3. 생성된 정책을 그대로 붙였더니 S3가 안 됩니다

- **증상**: Access Analyzer가 만들어준 정책으로 교체했더니 오브젝트 읽기·쓰기에서 `AccessDenied`가 납니다.
- **원인**: 정책 생성은 **데이터 이벤트를 분석하지 않습니다.** S3 오브젝트 액션은 애초에 후보에 오르지 않습니다. 같은 이유로 `iam:PassRole`도 빠집니다.
- **해법**: 생성 결과에 데이터 플레인 액션과 `PassRole`을 **손으로 채웁니다.** 그리고 스테이징에서 한 사이클 돌려본 뒤 프로덕션에 올립니다.

### 6-4. 권한은 줄였는데 위험은 그대로입니다

- **증상**: 액션 개수를 절반으로 줄여 리뷰를 통과했는데 침투 테스트에서 관리자 권한 획득 경로가 나옵니다.
- **원인**: 개수는 위험의 지표가 아닙니다. 2-4의 에스컬레이션 경로가 하나라도 남아 있으면 나머지를 아무리 줄여도 상한은 관리자입니다.
- **해법**: 리뷰 기준을 바꿉니다. "이 역할로 **다른 신원을 만들거나·바꾸거나·빌릴 수 있는가**"를 먼저 보고, 그다음에 개수를 봅니다. `check-access-not-granted`에 금지 액션 목록을 박아두면 자동화됩니다.

### 6-5. 정책이 문자 수 제한에 걸립니다

- **증상**: 액션을 하나하나 나열했더니 정책 저장이 거부됩니다.
- **원인**: 고객 관리형 정책 하나는 6,144자가 상한입니다. Access Analyzer도 생성 결과가 이 길이를 넘으면 정책을 여러 개로 쪼갭니다.
- **해법**: 정책을 쪼개기 전에 **역할을 쪼갤 때가 아닌지** 먼저 봅니다. 액션 수백 개가 필요한 역할은 대개 여러 일을 겸하고 있습니다.

## 7. 정리하면

- 권한은 **넓히는 방향으로만 압력이 있습니다.** 그래서 좁히는 작업은 절차로 강제하지 않으면 일어나지 않습니다.
- 좁히는 순서는 **Action → Resource → Condition**입니다. 한꺼번에 좁히면 무엇이 깨졌는지 알 수 없습니다.
- 필요한 액션은 추측이 아니라 **실행 기록에서 뽑습니다.** 단, 생성된 정책에는 데이터 이벤트와 `iam:PassRole`이 빠져 있습니다.
- 위험의 크기는 권한 개수가 아니라 **거기서 더 강해질 수 있는가**로 잽니다.
- 유지 장치는 **배포 전 `check-no-new-access`**, **배포 후 미사용 접근 분석기** 두 개입니다. 둘 다 사람의 기억에 의존하지 않는다는 점이 핵심입니다.

<!-- TODO: 확인 필요 — 4-2 예제의 `s3:AbortMultipartUpload` 포함 여부는 SDK와 업로드 방식(멀티파트 전환 임계값)에 따라 달라집니다. 사용하는 SDK 버전에서 실제로 발생하는 호출을 CloudTrail로 확인한 결과까지는 검증하지 못했습니다. -->

<!-- TODO: 확인 필요 — 6-5의 "생성 결과가 6,144자를 넘으면 여러 정책으로 분할"은 콘솔 정책 생성 화면 기준 동작입니다. CLI `get-generated-policy` 결과에서도 동일하게 분할되는지는 확인하지 못했습니다. -->

## 8. 참고자료

- [Security best practices in IAM](https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html)
- [IAM Access Analyzer policy generation](https://docs.aws.amazon.com/IAM/latest/UserGuide/access-analyzer-policy-generation.html)
- [Refine permissions in AWS using last accessed information](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_last-accessed.html)
- [IAM Access Analyzer findings](https://docs.aws.amazon.com/IAM/latest/UserGuide/access-analyzer-findings.html)
- [Create an unused access analyzer](https://docs.aws.amazon.com/IAM/latest/UserGuide/access-analyzer-create-unused.html)
- [Validate policies with custom policy checks](https://docs.aws.amazon.com/IAM/latest/UserGuide/access-analyzer-custom-policy-checks.html)
- [AWS global condition context keys](https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_condition-keys.html)
- [Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/reference_policies_actions-resources-contextkeys.html)
- 관련 문서: `day28-iam-basics.md` (User·Role·Policy와 판정 순서), `day22-sg-vs-nacl.md` (네트워크 경계의 허용·거부)
