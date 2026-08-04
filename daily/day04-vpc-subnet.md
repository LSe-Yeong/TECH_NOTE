# 네트워크를 왜 나누는가

> 이 문서가 답할 질문: **클라우드에서 네트워크를 왜 나누고, 어떤 기준으로 몇 개로 쪼개야 하는가?**
>
> 기준: Amazon VPC (2026년 8월 기준 사용자 가이드). 다른 클라우드도 이름만 다를 뿐 구조는 같습니다.

## 1. 핵심 개념

VPC(Virtual Private Cloud)는 **내가 소유한 IP 주소 대역 하나와, 그 대역 안에서만 통하는 라우팅 도메인**입니다. 서브넷은 그 대역을 잘라낸 조각이고, 조각 하나는 반드시 가용 영역(AZ) 하나 안에만 존재합니다.

여기까지는 정의입니다. 문제는 안 나눴을 때 벌어지는 일입니다.

계정을 만들면 리전마다 기본 VPC가 이미 있습니다. 구성이 이렇습니다.

| 항목 | 기본 VPC의 값 |
|---|---|
| VPC CIDR | `172.31.0.0/16` |
| 서브넷 | AZ마다 `/20` 하나씩 |
| 메인 라우팅 테이블 | `172.31.0.0/16 → local`, `0.0.0.0/0 → 인터넷 게이트웨이` |
| 서브넷의 퍼블릭 IP 자동 할당 | 켜짐 |

([Default VPC components](https://docs.aws.amazon.com/vpc/latest/userguide/default-vpc-components.html))

> 마지막 두 줄이 핵심입니다. **기본 VPC의 모든 서브넷은 퍼블릭 서브넷입니다.** 여기에 EC2를 띄우면 공인 IP가 붙고 인터넷에서 도달 가능해집니다. 웹 서버 하나만 띄울 때는 편합니다. 그런데 같은 자리에 DB를 띄우면, DB가 인터넷에 노출됩니다. 남은 방어선은 보안 그룹 규칙 한 줄뿐입니다. 디버깅하다 `0.0.0.0/0`으로 3306을 잠깐 연 뒤 되돌리는 걸 잊으면 그걸로 끝입니다.

네트워크를 나눈다는 건 **"규칙으로 막는다"를 "애초에 길이 없다"로 바꾸는 작업**입니다. 프라이빗 서브넷의 DB는 보안 그룹을 전부 열어도 인터넷에서 도달할 수 없습니다. 경로 자체가 없기 때문입니다.

## 2. 구조 — 나누는 축은 세 개다

서브넷을 나누는 이유는 하나가 아닙니다. 세 축이 동시에 작동하고, 서브넷 개수는 이 셋의 곱으로 정해집니다.

**축 1 — 라우팅 (인터넷에 닿는가)**

AWS 문서는 서브넷 타입을 이렇게 정의합니다. "서브넷 타입은 **라우팅을 어떻게 구성하느냐로 결정됩니다.**" ([Subnets for your VPC](https://docs.aws.amazon.com/vpc/latest/userguide/configure-subnets.html))

| 타입 | 조건 |
|---|---|
| 퍼블릭 | 인터넷 게이트웨이(IGW)로 가는 경로가 있음 |
| 프라이빗 | IGW 경로 없음. 나가려면 NAT 장치 필요 |
| Isolated | VPC 밖으로 나가는 경로가 아예 없음 |

`public`이라는 체크박스는 없습니다. **라우팅 테이블에 `0.0.0.0/0 → igw-xxx` 줄이 있으면 퍼블릭이고, 없으면 프라이빗입니다.** 이게 이 챕터에서 가장 중요한 한 문장입니다.

**축 2 — 가용 영역 (하나 죽어도 사는가)**

서브넷은 AZ를 넘지 못합니다. 그래서 2개 AZ를 쓰려면 같은 역할의 서브넷이 최소 2개 필요합니다. 이건 취향이 아니라 요구사항인 경우가 많습니다. RDS의 DB 서브넷 그룹은 **최소 두 개의 서로 다른 AZ**에 있는 서브넷을 요구하고 ([Working with a DB instance in a VPC](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_VPC.WorkingWithRDSInstanceinaVPC.html)), EKS 클러스터도 **서로 다른 두 AZ의 서브넷 두 개**를 요구합니다 ([EKS VPC and Subnet Considerations](https://docs.aws.amazon.com/eks/latest/best-practices/subnets.html)).

**축 3 — 역할 (누가 누구에게 말을 걸어야 하는가)**

웹 계층, 앱 계층, DB 계층을 다른 서브넷에 두면 보안 그룹뿐 아니라 네트워크 ACL로도 계층 간 통신을 제어할 수 있습니다. 더 실용적인 이유는 **의도가 코드에 드러난다**는 겁니다. `subnet-db-a`에 붙은 인스턴스는 DB라는 게 이름만 봐도 확실합니다.

세 축을 곱하면 서브넷 개수가 나옵니다. 2계층(퍼블릭/프라이빗) × 2 AZ = 4개가 최소 실무 구성이고, DB 계층을 분리하면 6개입니다.

## 3. 흐름

### 3-1. 코드로 보는 구성

```hcl
# main.tf — 2 AZ × 3 계층 = 6개 서브넷
resource "aws_vpc" "service" {
  cidr_block           = "10.20.0.0/16"
  enable_dns_hostnames = true
  tags                 = { Name = "service-stg" }
}

locals {
  azs = ["ap-northeast-2a", "ap-northeast-2c"]

  # 계층별로 큰 블록을 미리 예약합니다. 순서대로 붙이지 않습니다(5절).
  public_cidrs  = ["10.20.0.0/20", "10.20.16.0/20"]    # 10.20.0.0/18 구획
  app_cidrs     = ["10.20.64.0/20", "10.20.80.0/20"]   # 10.20.64.0/18 구획
  db_cidrs      = ["10.20.128.0/24", "10.20.129.0/24"] # 10.20.128.0/18 구획
}

resource "aws_subnet" "public" {
  count             = 2
  vpc_id            = aws_vpc.service.id
  cidr_block        = local.public_cidrs[count.index]
  availability_zone = local.azs[count.index]
  tags              = { Name = "public-${local.azs[count.index]}" }
}

resource "aws_subnet" "app" {
  count             = 2
  vpc_id            = aws_vpc.service.id
  cidr_block        = local.app_cidrs[count.index]
  availability_zone = local.azs[count.index]
  tags              = { Name = "app-${local.azs[count.index]}" }
}
```

퍼블릭·프라이빗을 가르는 건 서브넷 리소스가 아니라 라우팅 테이블입니다.

```hcl
resource "aws_internet_gateway" "service" {
  vpc_id = aws_vpc.service.id
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.service.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.service.id  # 이 한 줄이 퍼블릭을 만듭니다
  }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# app 서브넷용 라우팅 테이블은 AZ마다 따로 만듭니다.
# NAT를 한쪽 AZ에만 두면 그 AZ가 죽을 때 반대편 앱도 외부 호출이 끊깁니다.
resource "aws_route_table" "app" {
  count  = 2
  vpc_id = aws_vpc.service.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.service[count.index].id
  }
}
```

### 3-2. 실행 흐름

패킷이 서브넷을 떠날 때 일어나는 일은 단순합니다.

```text
1. 대상 IP 확인
2. 이 서브넷에 연결된 라우팅 테이블을 조회  ← 서브넷당 정확히 1개
3. 가장 긴 프리픽스가 일치하는 규칙을 선택
4. 그 규칙의 타깃(local / igw / nat / vgw)으로 전달
```

각 서브넷은 **반드시 라우팅 테이블 하나와 연결**되고, 명시하지 않으면 VPC의 메인 라우팅 테이블에 자동으로 붙습니다. 라우팅 테이블 하나를 여러 서브넷이 공유할 수는 있지만, 서브넷 하나가 두 개를 가질 수는 없습니다.

실제 요청은 이렇게 흐릅니다.

```text
[인바운드] 사용자 → IGW → ALB(public 서브넷) → 앱(app 서브넷) → RDS(db 서브넷)
[아웃바운드] 앱(app 서브넷) → NAT Gateway(public 서브넷) → IGW → 외부 API
```

아웃바운드에서 NAT Gateway가 **퍼블릭 서브넷에 있다**는 점을 놓치기 쉽습니다. NAT는 프라이빗 서브넷의 대리인이지, 프라이빗 서브넷의 구성요소가 아닙니다.

## 4. 특징

### 4-1. 얻는 것

- **실패 반경이 줄어듭니다.** 보안 그룹 오설정이 곧바로 인터넷 노출로 이어지지 않습니다. 프라이빗 서브넷에는 인바운드 경로 자체가 없습니다.
- **AZ 장애를 견딥니다.** 같은 역할의 서브넷이 2개 AZ에 있으면 한쪽이 사라져도 서비스가 삽니다.
- **감사와 대응이 쉬워집니다.** VPC Flow Logs를 서브넷 단위로 켤 수 있고, "DB 서브넷에서 나가는 아웃바운드"처럼 의미 있는 단위로 볼 수 있습니다.
- **의도가 인프라 코드에 남습니다.** 새로 합류한 사람이 `db` 서브넷에 웹 서버를 띄우려다 스스로 멈춥니다.

### 4-2. 지불하는 비용

| 비용 | 실제로 겪는 모습 |
|---|---|
| NAT Gateway 요금 | 프라이빗 서브넷이 외부로 나가려면 NAT가 필요합니다. 시간당 요금과 **처리한 데이터 GB당 요금이 따로** 붙습니다. AZ마다 하나씩 두면 그만큼 곱해집니다 ([VPC 요금](https://aws.amazon.com/vpc/pricing/)) |
| 운영 복잡도 | 라우팅 테이블·NAT·엔드포인트가 늘어납니다. 서버 3대짜리 서비스에 6개 서브넷은 과설계입니다 |
| 디버깅 난이도 | "왜 안 붙지"의 후보가 보안 그룹, NACL, 라우팅 테이블, DNS로 늘어납니다 |
| 되돌릴 수 없음 | **서브넷 CIDR은 만든 뒤 크기를 못 바꿉니다.** VPC의 기존 CIDR도 마찬가지입니다 (8절 함정 1) |

<!-- TODO: AZ 간 데이터 전송 요금(cross-AZ)이 멀티 AZ 구성의 실질 비용에 얼마나 기여하는지는 리전·서비스별 단가 확인이 필요합니다. 확인 전까지 수치를 쓰지 않았습니다. -->

### 4-3. 안 나눠도 되는 경우

토이 프로젝트, 사내 데모, 하루 만에 지울 환경이면 기본 VPC가 맞습니다. **다만 그 위에 프로덕션을 올리지 않는 것**이 조건입니다. 기본 VPC는 "시작을 빠르게" 최적화된 구성이고, 그 대가로 모든 서브넷이 인터넷을 향합니다.

## 5. 예제 — IP 설계

### 5-1. 흔한 구성 ❌

```hcl
# ❌ 모두가 쓰는 CIDR, 순서대로 붙인 /24
resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
}

resource "aws_subnet" "a" { cidr_block = "10.0.1.0/24" }  # web
resource "aws_subnet" "b" { cidr_block = "10.0.2.0/24" }  # app
resource "aws_subnet" "c" { cidr_block = "10.0.3.0/24" }  # db
resource "aws_subnet" "d" { cidr_block = "10.0.4.0/24" }  # 나중에 추가한 배치
```

문제가 세 겹입니다.

1. **`10.0.0.0/16`은 전 세계 기본값입니다.** 나중에 다른 팀 VPC와 피어링하거나 온프레미스와 연결할 때 대역이 겹칩니다. 겹치면 피어링 자체가 불가능하고, 해결책은 VPC를 다시 만드는 것뿐입니다.
2. **계층별 확장 공간이 없습니다.** app 서브넷을 늘리려는데 `10.0.3.0/24`는 이미 db가 쓰고 있습니다. 새 대역은 `10.0.5.0/24`가 되고, 라우팅 테이블과 NACL 규칙이 조각조각 흩어집니다.
3. **AZ 정보가 CIDR에 없습니다.** 로그에서 `10.0.2.37`을 봤을 때 어느 AZ의 무엇인지 알 수 없습니다.

### 5-2. 개선한 구성 ✔️

```hcl
# ✅ 두 번째 옥텟 = 환경, /18 구획 = 계층, 구획 안에서 = AZ
# dev 10.10.0.0/16 / stg 10.20.0.0/16 / prod 10.30.0.0/16
resource "aws_vpc" "service" {
  cidr_block = "10.20.0.0/16"
}
```

| 구획 | 용도 | AZ-a | AZ-c | 남는 공간 |
|---|---|---|---|---|
| `10.20.0.0/18` | 퍼블릭 | `10.20.0.0/20` | `10.20.16.0/20` | `/20` 두 개 |
| `10.20.64.0/18` | 앱 | `10.20.64.0/20` | `10.20.80.0/20` | `/20` 두 개 |
| `10.20.128.0/18` | DB | `10.20.128.0/24` | `10.20.129.0/24` | 넉넉 |
| `10.20.192.0/18` | 예약 | — | — | 전부 |

읽는 법이 규칙이 됩니다. `10.20.80.13`을 보면 **stg 환경, 앱 계층, 두 번째 AZ**라는 게 계산 없이 나옵니다. 계층마다 `/18`을 통째로 예약해뒀으니 AZ를 세 번째로 늘릴 때도 옆자리가 비어 있습니다.

DB 계층만 `/24`(251개 사용 가능)인 이유는 RDS 인스턴스가 수십 대가 될 일이 없기 때문입니다. **크기는 그 계층에 몇 개의 ENI가 생기는지로 정합니다.** 다만 RDS는 유지 관리·페일오버·컴퓨팅 확장 중에 여분 IP를 씁니다. AWS는 `10.0.0.0/24` 정도면 대개 충분하다고 안내하면서도, **각 서브넷에 최소 한 개의 주소를 RDS 복구용으로 남겨두라**고 명시합니다.

앱 계층이 `/20`(4091개)인 이유는 반대입니다. 오토스케일링과 컨테이너가 IP를 먹습니다. EKS의 VPC CNI는 **파드마다 VPC IP를 하나씩** 배정하므로, 노드 20대짜리 클러스터가 `/24` 서브넷을 순식간에 비웁니다.

## 6. 이 설계가 지키는 원칙 — 경계는 선언이 아니라 경로다

보안 그룹은 **"통과시킬지 말지"를 매번 판단하는 규칙**입니다. 규칙은 사람이 바꿉니다. 그리고 사람은 새벽 3시에 장애 대응하다 규칙을 바꿉니다.

서브넷 분리는 **경로의 유무**입니다. 프라이빗 서브넷의 라우팅 테이블에 IGW가 없으면, 그 서브넷의 인스턴스는 보안 그룹을 전부 열어도 인터넷에서 도달되지 않습니다. 판단이 개입할 여지가 없습니다.

```hcl
# ❌ 퍼블릭 서브넷의 DB. 방어선이 보안 그룹 하나뿐입니다.
resource "aws_db_instance" "orders" {
  db_subnet_group_name = aws_db_subnet_group.public_subnets.name
  publicly_accessible  = true
}

# ✅ 프라이빗 서브넷의 DB. 보안 그룹은 두 번째 방어선이 됩니다.
resource "aws_db_instance" "orders" {
  db_subnet_group_name = aws_db_subnet_group.db_tier.name  # IGW 경로 없는 서브넷
  publicly_accessible  = false
}
```

RDS 문서도 같은 순서로 말합니다. DB 인스턴스가 퍼블릭이 되려면 **DB 서브넷 그룹의 모든 서브넷에 인터넷 게이트웨이가 있어야** 합니다. 즉 `publicly_accessible = true`만으로는 부족하고, 라우팅이 허락해야 성립합니다. 반대로 라우팅이 없으면 플래그가 무의미해집니다.

**규칙은 실수할 수 있고, 경로는 실수할 수 없습니다.** 두 계층을 다 쌓되, 바깥쪽을 경로로 만드는 게 이 설계의 요점입니다.

## 7. 함정

### 함정 1 — 서브넷이 꽉 찼는데 늘릴 수가 없습니다

- **증상**: 오토스케일링이 인스턴스를 못 띄웁니다. 이벤트 로그에 `InsufficientFreeAddressesInSubnet`이 찍힙니다. EKS라면 파드가 `ContainerCreating`에서 멈춥니다. 콘솔에서 서브넷 CIDR을 늘리려는데 **수정 버튼이 없습니다.**
- **원인**: AWS는 **기존 CIDR 블록의 크기를 늘리거나 줄이는 것을 허용하지 않습니다.** VPC도, 서브넷도 마찬가지입니다. 게다가 서브넷마다 **처음 4개와 마지막 1개, 총 5개 주소가 예약**되어 있습니다. `/24`는 251개, `/28`은 11개만 쓸 수 있습니다. `/28`이 서브넷의 최소 크기입니다.
- **해법**: 늘리는 게 아니라 **옆에 새 서브넷을 만듭니다.** 5-2처럼 계층별 구획을 예약해뒀다면 같은 구획 안에서 새 `/20`을 잘라 쓰면 됩니다. VPC 자체가 꽉 찼다면 보조 CIDR 블록을 붙입니다(기본 5개, 최대 50개까지 상향 가능). 근본 해법은 처음에 **쓸 것 같은 크기의 4배**로 잡는 것입니다. 사설 IP는 공짜고, 다시 만드는 건 무중단이 아닙니다.

### 함정 2 — 보조 CIDR을 붙이려는데 거부당합니다

- **증상**: VPC가 `10.50.0.0/16`인데 IP가 부족해 `172.16.0.0/16`을 보조 CIDR로 추가하려 합니다. API가 거부합니다.
- **원인**: **RFC 1918 대역을 섞을 수 없습니다.** 기존 CIDR이 `10.0.0.0/8` 범위면 `172.16.0.0/12`와 `192.168.0.0/16`에서는 보조 CIDR을 추가하지 못합니다. AWS가 교차 계정·교차 VPC 기능 내부에서 쓰는 대역과 충돌하지 않도록 건 제약입니다. `198.19.0.0/16`도 전 범위에서 금지입니다.
- **해법**: 같은 RFC 1918 대역 안에서 겹치지 않는 블록을 고릅니다(`10.50.0.0/16` → `10.51.0.0/16`). 그것도 어려우면 **`100.64.0.0/10`(CG-NAT 대역)을 씁니다.** 이 대역은 어느 기존 대역과도 조합이 허용되고, 파드처럼 VPC 밖으로 라우팅될 필요가 없는 워크로드를 담기에 적합합니다. ([IPv4 CIDR block association restrictions](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-cidr-blocks.html))

### 함정 3 — 프라이빗 서브넷에 뒀는데 공인 IP가 붙어 요금이 나옵니다

- **증상**: 청구서에 `PublicIPv4:InUseAddress` 항목이 계속 늘어납니다. 인스턴스는 분명 프라이빗 계층에 있습니다.
- **원인**: 서브넷의 **퍼블릭 IP 자동 할당 속성**이 켜져 있으면 그 서브넷에서 만들어지는 네트워크 인터페이스에 공인 IPv4가 붙습니다. 라우팅과는 별개의 설정입니다. 기본 VPC를 복사해 만들었거나 콘솔 마법사로 만들면 켜진 채로 남기 쉽습니다. 그리고 **2024년 2월 1일부터 공인 IPv4 주소는 사용 중이든 유휴든 시간당 $0.005가 과금됩니다.** ([New — AWS Public IPv4 Address Charge](https://aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-public-ip-insights/))
- **해법**: 프라이빗 서브넷은 `map_public_ip_on_launch = false`로 못 박습니다. 이미 붙은 것은 인터페이스를 다시 만들어야 떨어집니다. 이 설정을 Terraform에 명시해두면 콘솔에서 누가 켜도 다음 `apply`에서 되돌아옵니다.

### 함정 4 — 서브넷은 나눴는데 AZ가 하나입니다

- **증상**: 퍼블릭/프라이빗/DB로 잘 나눈 VPC인데 RDS 생성 단계에서 막힙니다. 또는 AZ 한 곳에 장애가 났을 때 서비스 전체가 내려갑니다.
- **원인**: 서브넷을 **계층으로만 나누고 AZ로는 안 나눈** 경우입니다. 서브넷은 AZ를 넘을 수 없으므로, 계층 3개 × AZ 1개는 그냥 단일 AZ 구성입니다. RDS의 DB 서브넷 그룹은 최소 두 AZ를 요구하므로 여기서 걸립니다. EKS도 서로 다른 두 AZ의 서브넷 두 개를 요구합니다.
- **해법**: **계층 × AZ**로 곱해서 만듭니다. 최소 2 AZ, 리전에 세 개 이상 있다면 3 AZ가 안전합니다. NAT Gateway도 AZ마다 하나씩 둡니다. 한쪽 AZ의 NAT를 공유하면 그 AZ가 죽었을 때 반대편 앱의 외부 호출이 함께 끊기고, 평소에도 AZ 간 전송 비용이 붙습니다. 3-1의 `aws_route_table.app`을 `count = 2`로 만든 이유가 이겁니다.

### 함정 5 — 특정 대역을 골랐다가 컨테이너가 통신을 못 합니다

- **증상**: VPC를 `172.17.0.0/16`으로 만들었더니 일부 관리형 서비스나 Docker를 쓰는 인스턴스에서 통신이 끊깁니다.
- **원인**: **`172.17.0.0/16`은 Docker의 기본 브리지 대역**이고, AWS Cloud9·SageMaker AI 같은 서비스도 이 대역을 씁니다. 호스트의 IP 대역과 컨테이너 브리지 대역이 겹치면 라우팅이 어느 쪽으로 갈지 뒤섞입니다. AWS 문서도 이 대역을 VPC에 쓰지 말라고 명시합니다.
- **해법**: `172.17.0.0/16`을 피합니다. `10.x`에서 조직 전체의 대역 할당표를 만들고 환경·계정별로 미리 배분해두는 게 정석입니다. VPC를 만드는 시점은 **되돌리기가 가장 싼 유일한 시점**입니다.

## 8. 알아두면 좋은 한도

기본값이고 대부분 상향 가능하지만, 설계할 때 머릿속에 있어야 하는 숫자들입니다. ([Amazon VPC quotas](https://docs.aws.amazon.com/vpc/latest/userguide/amazon-vpc-limits.html))

| 항목 | 기본값 |
|---|---|
| 리전당 VPC | 5 |
| VPC당 서브넷 | 200 |
| VPC당 IPv4 CIDR 블록 | 5 (최대 50까지 상향) |
| VPC당 라우팅 테이블 | 200 |
| 라우팅 테이블당 라우트 | 500 |
| 네트워크 인터페이스당 보안 그룹 | 5 |
| 보안 그룹당 인바운드/아웃바운드 규칙 | 각 60 |

서브넷 200개는 넉넉해 보이지만, **라우팅 테이블당 라우트 500개**는 Transit Gateway로 수십 개 VPC를 연결하기 시작하면 실제로 마주치는 벽입니다.

## 9. 참고자료

- [VPC CIDR blocks](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-cidr-blocks.html) — 허용 크기, RFC 1918 권고, 보조 CIDR 조합 제약
- [Subnet CIDR blocks](https://docs.aws.amazon.com/vpc/latest/userguide/subnet-sizing.html) — `/28`~`/16` 범위, 예약된 5개 주소
- [Subnets for your VPC](https://docs.aws.amazon.com/vpc/latest/userguide/configure-subnets.html) — 서브넷 타입이 라우팅으로 결정된다는 정의
- [Default VPC components](https://docs.aws.amazon.com/vpc/latest/userguide/default-vpc-components.html) — 기본 VPC의 실제 구성
- [Amazon VPC quotas](https://docs.aws.amazon.com/vpc/latest/userguide/amazon-vpc-limits.html) — 8절 한도 표
- [New — AWS Public IPv4 Address Charge](https://aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-public-ip-insights/) — 함정 3의 과금 시점과 단가
- [EKS — VPC and Subnet Considerations](https://docs.aws.amazon.com/eks/latest/best-practices/subnets.html) — 컨테이너 환경의 IP 소모와 서브넷 설계
