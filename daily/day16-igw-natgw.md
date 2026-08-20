# 들어오는 문과 나가는 문은 다릅니다 — IGW와 NAT Gateway

> 이 문서가 답할 질문: **인터넷으로 나가는 길과 인터넷에서 들어오는 길은 왜 서로 다른 장치로 나뉘어 있고, 각 장치는 무엇을 할 수 있고 무엇을 못 하는가?**
>
> 기준: Amazon VPC 사용자 가이드 (2026년 8월 확인). `day04-vpc-subnet.md`가 "왜 나누는가", `day10-route-table.md`가 "나눈 것의 실체는 라우팅 테이블"을 다뤘다면, 이 문서는 **나눠진 서브넷이 바깥과 어떻게 통신하는가**를 다룹니다.

## 1. 핵심 개념

VPC에서 인터넷과 연결되는 장치는 성격이 두 가지입니다.

- **인터넷 게이트웨이(IGW, Internet Gateway)** — 양방향 문. 나갈 수도 있고, 밖에서 들어올 수도 있습니다.
- **NAT 게이트웨이(NAT Gateway)** — 나가기 전용 문. 안에서 시작한 연결만 통과합니다.

> 흔한 오해가 "NAT 게이트웨이는 IGW의 싼 버전"이라는 것입니다. 정반대입니다. IGW는 **무료**이고 NAT 게이트웨이는 **시간당·GB당 과금**됩니다. 그런데도 NAT를 돈 주고 쓰는 이유는 단 하나, **밖에서 먼저 말을 걸 수 없게 만들기 위해서**입니다. 애플리케이션 서버는 패키지를 받고 외부 API를 호출해야 하니 나가야는 합니다. 하지만 인터넷에서 그 서버로 직접 연결이 열리면 안 됩니다. 이 두 요구는 IGW 하나로는 동시에 만족시킬 수 없습니다. **IGW를 붙이는 순간 나가는 길과 들어오는 길이 한꺼번에 열리기 때문입니다.**

방향을 분리할 수 없는 장치와 분리할 수 있는 장치. 이게 두 리소스가 따로 존재하는 이유의 전부입니다.

## 2. 구조

### 2-1. IGW — 라우팅 타깃이면서 동시에 1:1 NAT

IGW가 하는 일은 두 가지입니다.

1. **라우팅 테이블의 타깃**이 됩니다. `0.0.0.0/0 → igw-xxx` 라우트를 만들 수 있는 대상이 됩니다.
2. **IPv4에 대해 1:1 NAT를 수행합니다.**

두 번째가 덜 알려져 있습니다. EC2 인스턴스의 OS는 **자기 퍼블릭 IP를 모릅니다.** `ip addr`을 찍어보면 사설 IP만 나옵니다. IGW가 나가는 패킷의 출발지 주소를 퍼블릭 IPv4 또는 Elastic IP로 바꾸고, 들어오는 패킷의 목적지 주소를 사설 IP로 되돌립니다. 인스턴스 하나에 퍼블릭 주소 하나가 대응하므로 1:1입니다.

IPv6는 다릅니다. IPv6 주소는 전역에서 유일하고 기본적으로 공인 주소이므로, IGW는 IPv6에 대해 NAT를 하지 않고 그냥 전달만 합니다.

특징 몇 가지가 중요합니다.

- **수평 확장되고 이중화되어 있습니다.** 대역폭 병목이나 가용성 위험 지점이 되지 않습니다. AZ에 속하지 않습니다.
- **VPC당 하나만 붙습니다.** 리전당 기본 5개이고, VPC당 동시에 연결할 수 있는 IGW는 1개입니다.
- **요금이 없습니다.** IGW 자체는 무료이고, 데이터 전송 요금만 EC2 쪽에서 붙습니다.

### 2-2. NAT 게이트웨이 — 다대일 변환과 상태 테이블

NAT 게이트웨이는 여러 사설 IP를 **주소 하나 뒤로 숨깁니다.** 이때 출발지 포트를 바꿔가며 연결을 구분하므로, 사실상 PAT(Port Address Translation)입니다.

동작 순서가 조금 특이합니다. 공인 NAT 게이트웨이라도 **NAT 게이트웨이 자신은 사설 IP까지만 바꿉니다.** 인스턴스의 사설 IP → NAT 게이트웨이의 사설 IP로 바꾼 뒤, 그다음 **IGW가** NAT 게이트웨이의 사설 IP를 Elastic IP로 바꿉니다. 그래서 공인 NAT 게이트웨이는 **같은 VPC에 IGW가 붙어 있어야 만들어집니다.** IGW 없이 만들려고 하면 생성이 `Failed`로 끝나고 `Network vpc-xxxxxxxx has no internet gateway attached` 메시지가 남습니다.

- **AZ에 속하는 자원입니다.** 해당 AZ 안에서는 이중화되어 있지만, AZ가 죽으면 그 NAT를 쓰던 다른 AZ의 리소스까지 인터넷이 끊깁니다. IGW와 결정적으로 다른 점입니다.
- **보안 그룹을 붙일 수 없습니다.** 요청자 관리형 ENI가 하나 생기지만 속성을 바꿀 수 없습니다. 제어는 서브넷의 네트워크 ACL과 뒤에 있는 인스턴스의 보안 그룹으로 합니다.
- **상태를 유지합니다(stateful).** 나간 요청에 대한 응답은 자동으로 돌아옵니다.
- **TCP·UDP·ICMP만 지원합니다.** IPsec(ESP)은 통과하지 못합니다.

### 2-3. 공인 NAT와 사설 NAT

연결 유형(connectivity type)을 둘 중 하나로 고릅니다.

| | 공인(Public) | 사설(Private) |
|---|---|---|
| 어디에 두나 | 퍼블릭 서브넷 | 아무 서브넷 |
| Elastic IP | 생성 시 필수 | 붙일 수 없음 |
| 나가는 곳 | IGW를 거쳐 인터넷 | Transit Gateway / 가상 프라이빗 게이트웨이 |
| 목적 | 인터넷 아웃바운드 | 온프레미스·다른 VPC와 **IP 대역 충돌 회피** |

사설 NAT 게이트웨이는 인터넷과 무관합니다. 온프레미스와 VPC의 사설 대역이 겹칠 때 출발지 주소를 한 개로 정리해서 보내는 용도입니다. 사설 NAT의 트래픽을 IGW로 라우팅하면 **IGW가 그 트래픽을 버립니다.** 오류가 아니라 조용히 드롭입니다.

### 2-4. Egress-only 인터넷 게이트웨이 — IPv6 전용 나가기 문

IPv6에는 NAT가 필요 없습니다. 주소가 부족하지 않으니까요. 그런데 "나가기만 되고 들어오기는 막고 싶다"는 요구는 IPv6에서도 그대로 남습니다. 그래서 별도 리소스가 있습니다.

- IPv6 전용입니다. `::/0 → eigw-xxx` 라우트로 씁니다.
- 상태를 유지합니다. 나간 요청의 응답은 돌아옵니다.
- **IGW처럼 수평 확장·이중화되어 있고, 요금이 없습니다.** NAT 게이트웨이와 달리 시간당 요금이 붙지 않습니다.
- 보안 그룹을 붙일 수 없고, 네트워크 ACL로 제어합니다.

IPv6 워크로드가 IPv4 전용 서비스를 호출해야 한다면 얘기가 다릅니다. 그건 NAT 게이트웨이의 NAT64와 Route 53 Resolver의 DNS64 조합을 씁니다.

## 3. 흐름

### 3-1. 패킷 따라가기

퍼블릭 서브넷의 EC2가 `example.com:443`으로 나가는 경우입니다.

```text
EC2(10.20.1.10) → 서브넷 라우터 → 라우팅 테이블(0.0.0.0/0 → igw)
   → IGW: 출발지를 10.20.1.10 → 198.51.100.7(EIP)로 치환
   → 인터넷
응답: 목적지 198.51.100.7 → IGW가 10.20.1.10으로 되돌림 → EC2
```

프라이빗 서브넷의 EC2가 같은 곳으로 나가는 경우입니다.

```text
EC2(10.20.10.30) → 라우팅 테이블(0.0.0.0/0 → nat)
   → NAT GW(10.20.1.200): 출발지를 10.20.10.30:51234 → 10.20.1.200:31002 로 치환하고
                           변환 정보를 상태 테이블에 기록
   → NAT GW가 속한 퍼블릭 서브넷의 라우팅 테이블(0.0.0.0/0 → igw)
   → IGW: 10.20.1.200 → 198.51.100.9(NAT의 EIP)
   → 인터넷
```

여기서 두 가지가 드러납니다.

- 라우팅 테이블이 **두 번** 조회됩니다. 프라이빗 서브넷 것과 NAT가 있는 퍼블릭 서브넷 것. 둘 중 하나만 잘못돼도 안 나갑니다.
- 반대 방향, 즉 인터넷에서 `198.51.100.9`로 먼저 연결을 시도하면 **NAT의 상태 테이블에 대응하는 항목이 없어서 버려집니다.** 방화벽 규칙이 막는 게 아니라, 돌려보낼 사설 주소를 알 방법이 없어서 못 보내는 겁니다. 규칙이 아니라 구조라서 실수로 열릴 수 없습니다.

### 3-2. 코드로 보는 구성

```hcl
resource "aws_vpc" "service" {
  cidr_block = "10.20.0.0/16"
  tags       = { Name = "service-prod" }
}

resource "aws_internet_gateway" "service" {
  vpc_id = aws_vpc.service.id
}

# NAT는 AZ 자원입니다. AZ마다 하나씩 둡니다.
resource "aws_eip" "nat" {
  count  = 2
  domain = "vpc"
}

resource "aws_nat_gateway" "service" {
  count         = 2
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id   # 퍼블릭 서브넷에 둡니다
  connectivity_type = "public"

  # IGW가 붙기 전에 만들면 생성이 실패합니다
  depends_on = [aws_internet_gateway.service]
}

# 퍼블릭 서브넷용 — 여기가 igw를 가리킵니다
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.service.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.service.id
  }
}

# 프라이빗 서브넷용 — AZ마다 자기 AZ의 NAT를 가리킵니다
resource "aws_route_table" "private" {
  count  = 2
  vpc_id = aws_vpc.service.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.service[count.index].id
  }
}
```

`depends_on`이 붙은 이유가 2-2에서 말한 제약입니다. Terraform은 `aws_nat_gateway`와 `aws_internet_gateway` 사이에 참조 관계가 없어서 순서를 스스로 알지 못합니다. 명시하지 않으면 첫 `apply`에서 간헐적으로 NAT 생성이 실패합니다.

## 4. 무엇을 고를 것인가

### 4-1. 세 장치 비교

| | IGW | NAT Gateway (공인) | Egress-only IGW |
|---|---|---|---|
| 프로토콜 | IPv4 · IPv6 | IPv4 (IPv6는 NAT64) | IPv6만 |
| 방향 | 양방향 | 아웃바운드만 | 아웃바운드만 |
| 요금 | 없음 | 시간당 + GB당 | 없음 |
| AZ 종속 | 없음 | 있음(존 모드 기준) | 없음 |
| 대역폭 | 제한 없음 | 5 Gbps에서 100 Gbps까지 자동 확장 | 제한 없음 |
| 보안 그룹 | 해당 없음 | 붙일 수 없음 | 붙일 수 없음 |

### 4-2. 판단 기준

- 인터넷에서 **먼저 연결이 들어와야 하는가** → IGW. ALB, 공개 API 게이트웨이가 여기 해당합니다.
- 나가기만 하면 되는가 → IPv4면 NAT 게이트웨이, IPv6면 Egress-only IGW.
- 나가는 대상이 대부분 **AWS 서비스**인가 → 뒤의 함정 3을 먼저 읽습니다. NAT를 안 거치는 길이 있습니다.
- 온프레미스와 IP 대역이 겹치는가 → 사설 NAT 게이트웨이.

### 4-3. NAT 게이트웨이의 트레이드오프

공짜가 아닙니다. 세 가지를 지불합니다.

1. **요금.** 미국 동부(오하이오) 기준 시간당 $0.045, 처리 데이터 GB당 $0.045입니다([Amazon VPC 요금](https://aws.amazon.com/vpc/pricing/), 2026년 8월 확인). AZ 3개면 아무것도 안 보내도 NAT만으로 월 100달러 근처입니다. 여기에 Elastic IP는 2024년 2월 1일부터 **사용 중이어도** 시간당 $0.005가 붙습니다([AWS 공지](https://aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-public-ip-insights/)).
2. **가용성 결합.** AZ 자원이라 AZ마다 만들어야 하고, 그러면 1번 비용이 AZ 수만큼 곱해집니다. 하나만 쓰면 그 AZ가 곧 단일 장애점입니다.
3. **기능 제약.** 포트 포워딩이 없고, 보안 그룹을 못 붙이고, TCP·ICMP 조각화 패킷을 버립니다.

## 5. 예제 — NAT를 하나만 두는 구성

### 5-1. 흔한 구성 ❌

```hcl
# ❌ 비용을 아끼려고 NAT 하나, 프라이빗 라우팅 테이블도 하나
resource "aws_nat_gateway" "single" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public_a.id   # AZ-a 에만 존재
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.service.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.single.id
  }
}
# AZ-a, AZ-c 의 프라이빗 서브넷이 모두 이 테이블을 씁니다
```

평소에는 잘 돕니다. 두 가지가 숨어 있습니다.

- AZ-c의 앱이 외부를 호출할 때마다 트래픽이 **AZ를 건너갔다가** 나갑니다. NAT 데이터 처리 요금 위에 AZ 간 데이터 전송 요금이 얹힙니다.
- AZ-a에 장애가 나면 AZ-c의 앱도 외부 호출이 전부 끊깁니다. **멀티 AZ로 구성했는데 아웃바운드는 싱글 AZ입니다.**

### 5-2. 개선한 구성 ✔️

```hcl
# ✅ AZ마다 NAT, AZ마다 라우팅 테이블
resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id  # 같은 AZ의 NAT
}
```

3-2의 구성이 그대로 답입니다. 라우팅 테이블 하나에는 `0.0.0.0/0`을 하나만 넣을 수 있으므로, **AZ별 NAT를 쓰려면 라우팅 테이블도 반드시 AZ별로 갈라야 합니다.** NAT만 3개 만들고 라우팅 테이블을 공유하면 돈만 3배 내고 아무것도 개선되지 않습니다.

비용 때문에 NAT를 하나만 두기로 했다면, 그건 **가용성을 의식적으로 판 것**이어야 합니다. 스테이징 환경에서는 합리적인 선택입니다. 프로덕션에서 모르고 그렇게 되어 있는 것과는 다릅니다.

## 6. 리전 모드 NAT 게이트웨이

2025년 11월에 NAT 게이트웨이에 **리전 가용성 모드**가 추가됐습니다([AWS 공지](https://aws.amazon.com/about-aws/whats-new/2025/11/aws-nat-gateway-regional-availability)). 5절의 문제를 구조적으로 없애는 방향입니다.

- NAT 게이트웨이 **ID 하나**를 모든 AZ의 프라이빗 서브넷이 라우팅 타깃으로 씁니다. AZ별로 테이블을 가를 필요가 없어집니다.
- **퍼블릭 서브넷이 필요 없습니다.** 독립 리소스로 만들어지고 AWS가 IGW로 가는 라우트가 들어간 전용 라우팅 테이블을 자동 생성합니다.
- 워크로드가 있는 AZ를 감지해 자동으로 확장·축소합니다. 다만 새 AZ에 리소스를 띄운 뒤 **확장이 완료되기까지 최대 60분**이 걸리고, 그동안은 기존 AZ의 NAT가 AZ를 건너 처리합니다.
- IP 주소를 AZ당 최대 32개까지 가질 수 있습니다(존 모드는 8개). 뒤의 함정 1이 훨씬 늦게 옵니다.

제약도 분명합니다. **사설 NAT를 지원하지 않고**, 용량이 제한된 AZ에서는 쓸 수 없습니다. 존 모드에서 리전 모드로 바꾸는 작업은 기존 연결을 끊습니다.

<!-- TODO: 리전 모드의 요금 체계가 존 모드와 동일한지(시간당 $0.045 + GB당 $0.045) AWS 요금 페이지에서 별도 항목으로 확인되지 않았습니다. 확인 전까지 수치를 쓰지 않았습니다. -->

## 7. 함정

### 함정 1 — `ErrorPortAllocation`이 튀고 연결이 실패합니다

- **증상**: 평소엔 멀쩡하다가 트래픽이 몰리면 외부 API 호출이 간헐적으로 실패합니다. CloudWatch의 NAT 게이트웨이 지표 `ErrorPortAllocation`이 0이 아닙니다.
- **원인**: **IPv4 주소 하나당, 고유 목적지 하나당 동시 연결 55,000개**가 상한입니다. 여기서 고유 목적지는 목적지 IP·목적지 포트·프로토콜의 조합입니다. 그래서 서로 다른 사이트를 부를 때는 잘 버티다가, **결제 게이트웨이 한 곳에 커넥션을 몰아 여는 순간** 그 조합 하나에서 포트가 고갈됩니다. 커넥션 풀을 쓰지 않고 매 요청마다 새 연결을 여는 HTTP 클라이언트가 전형적인 원인입니다.
- **해법**: 근본 해법은 클라이언트 쪽 커넥션 재사용입니다. 인프라에서 늘리려면 NAT 게이트웨이에 보조 IPv4 주소를 추가합니다. 주소 하나당 55,000이 더해지고, 존 모드는 최대 8개(기본 1 + 보조 7), 리전 모드는 AZ당 32개까지입니다. 공인 NAT의 Elastic IP는 기본 2개이고 쿼터 상향으로 8개까지 올립니다. `IdleTimeoutCount` 지표로 놀고 있는 연결이 늘고 있는지도 함께 봅니다.

### 함정 2 — 350초마다 연결이 끊깁니다

- **증상**: 긴 배치 쿼리나 유휴 시간이 긴 커넥션이 일정하게 끊깁니다. 애플리케이션 로그에 `Connection reset by peer`가 남습니다. 재현하면 항상 350초 근처입니다.
- **원인**: **NAT 게이트웨이는 350초 이상 유휴 상태인 연결을 정리합니다.** 그리고 이때 `FIN`이 아니라 `RST`를 보냅니다. 정상 종료가 아니라 강제 리셋이라, 애플리케이션 입장에서는 "갑자기 끊겼다"로 보입니다. NAT 인스턴스는 `FIN`을 보내므로 NAT 인스턴스에서 NAT 게이트웨이로 옮긴 뒤 이 증상이 처음 나타나기도 합니다.
- **해법**: 인스턴스에서 **TCP keepalive를 350초보다 짧게** 설정합니다. 커넥션 풀을 쓴다면 풀의 유휴 커넥션 검증 주기나 최대 유휴 시간을 350초 아래로 맞추는 쪽이 더 확실합니다. DB 커넥션이라면 애초에 NAT를 지나지 않게 하는 게 정답입니다.

### 함정 3 — NAT 데이터 처리 요금이 S3 트래픽으로 채워집니다

- **증상**: 청구서에서 NAT 게이트웨이 데이터 처리 항목이 계속 늘어납니다. 외부 호출은 별로 없는데 그렇습니다.
- **원인**: S3, DynamoDB, ECR, CloudWatch Logs 같은 **AWS 서비스 호출도 프라이빗 서브넷에서는 NAT를 지납니다.** 공개 엔드포인트 주소로 가기 때문에 `0.0.0.0/0` 라우트에 매칭됩니다. 컨테이너 이미지를 ECR에서 당길 때마다, 로그를 CloudWatch로 보낼 때마다 GB당 요금이 붙습니다.
- **해법**: **VPC 엔드포인트**로 우회시킵니다. S3와 DynamoDB는 게이트웨이 엔드포인트가 있고, 라우팅 테이블에 라우트가 자동으로 추가되며 엔드포인트 자체 요금이 없습니다. 나머지 서비스는 인터페이스 엔드포인트(PrivateLink)이고 시간당·GB당 요금이 따로 있으므로, **트래픽 양을 먼저 재고 NAT 처리 요금과 비교한 뒤** 결정합니다. AWS 문서도 NAT 요금 절감 전략으로 이 둘을 명시합니다.

### 함정 4 — IGW를 붙였는데 인터넷이 안 됩니다

- **증상**: IGW를 만들어 VPC에 붙이고 라우팅 테이블에 `0.0.0.0/0 → igw`도 넣었는데 EC2가 외부와 통신하지 못합니다.
- **원인**: IPv4로 나가려면 인스턴스에 **퍼블릭 IPv4 주소나 Elastic IP가 있어야 합니다.** 기본 VPC가 아닌 직접 만든 VPC의 서브넷은 퍼블릭 IP 자동 할당이 꺼져 있는 것이 기본값입니다. 서브넷 이름을 `public-a`로 지어도 자동 할당이 꺼져 있으면 인스턴스는 사설 IP만 받고, IGW는 변환할 대상이 없습니다. IPv6라면 원인이 다릅니다. VPC와 서브넷에 IPv6 CIDR이 있고 인스턴스에 IPv6 주소가 배정되어 있어야 하며, **`0.0.0.0/0` 라우트는 IPv6 트래픽을 전혀 커버하지 않으므로 `::/0` 라우트를 따로 만들어야 합니다.**
- **해법**: 서브넷의 퍼블릭 IPv4 자동 할당 설정(`map_public_ip_on_launch`)을 확인합니다. 다만 켤 대상인지부터 판단해야 합니다. **ALB 뒤에 있는 앱 서버라면 애초에 퍼블릭 IP가 필요 없습니다.** 주소마다 시간당 요금이 붙는 것도 이유지만, 더 중요한 건 퍼블릭 IP가 붙는 순간 인바운드 경로가 생긴다는 점입니다.

### 함정 5 — NAT 게이트웨이 뒤로 접속하려고 합니다

- **증상**: 프라이빗 서브넷의 서버에 접근하려고 NAT의 Elastic IP로 SSH를 시도합니다. 응답이 없습니다. NAT의 EIP로 `ping`을 보내도 응답이 없습니다.
- **원인**: NAT 게이트웨이는 **VPC 안에서 시작한 연결만** 통과시킵니다. 포트 포워딩 기능이 없고, 배스천 호스트로 쓸 수도 없습니다. NAT 자체에 대한 `ping`도 답하지 않습니다. 설정 문제가 아니라 지원하지 않는 기능입니다. 여기서 헷갈리기 쉬운 사례가 하나 더 있는데, **VPC 피어링을 거쳐 NAT 게이트웨이로 라우팅하는 것도 불가능합니다.** 반대로 NAT를 거친 뒤 피어링으로 나가는 방향은 됩니다.
- **해법**: 관리 접근은 AWS Systems Manager Session Manager를 씁니다. 인바운드 포트를 하나도 열지 않고 SSM 엔드포인트로 나가는 아웃바운드만으로 셸을 붙일 수 있습니다. 포트 포워딩이나 배스천이 반드시 필요하면 NAT 게이트웨이가 아니라 NAT 인스턴스를 직접 운영해야 하는데, 그러면 패치·페일오버·대역폭이 전부 다시 내 책임이 됩니다.

### 함정 6 — 인바운드를 계정 차원에서 막고 싶습니다

- **증상**: 계정이 여러 개고 팀도 여러 개입니다. 누군가 실수로 IGW 라우트가 있는 서브넷에 내부용 서버를 띄웁니다. 리뷰로 잡는 데 한계가 있습니다.
- **원인**: 라우팅 테이블과 보안 그룹은 **VPC 단위의 개별 설정**입니다. 계정 전체에 "인바운드 금지"를 선언할 수단이 아닙니다.
- **해법**: **VPC 퍼블릭 액세스 차단(VPC BPA)** 을 씁니다. 리전 단위로 두 가지 모드가 있습니다. `Bidirectional`은 IGW와 Egress-only IGW의 모든 트래픽을 막고, `Ingress-only`는 들어오는 트래픽만 막습니다. `Ingress-only` 모드에서는 NAT 게이트웨이와 Egress-only IGW를 지나는 아웃바운드가 그대로 살아 있습니다. 이 문서의 주제를 계정 정책으로 표현한 셈입니다. 예외가 필요한 VPC나 서브넷은 제외(exclusion)로 지정합니다. 먼저 영향도를 평가해보고 적용하는 것이 안전합니다.

## 8. 알아두면 좋은 한도

([Amazon VPC quotas](https://docs.aws.amazon.com/vpc/latest/userguide/amazon-vpc-limits.html), 2026년 8월 확인)

| 항목 | 기본값 | 비고 |
|---|---:|---|
| 리전당 IGW | 5 | VPC 쿼터를 올리면 함께 올라갑니다. VPC당 1개만 연결 |
| 리전당 Egress-only IGW | 5 | VPC당 1개만 연결 |
| AZ당 NAT 게이트웨이 | 5 | `pending`·`active`·`deleting` 상태가 쿼터를 차지합니다 |
| NAT 게이트웨이당 사설 IP | 8 | 조정 가능 |
| 공인 NAT 게이트웨이당 Elastic IP | 2 | 최대 8까지 상향 요청 |
| 리전당 Elastic IP | 5 | 조정 가능 |

## 9. 참고자료

- [Enable internet access for a VPC using an internet gateway](https://docs.aws.amazon.com/vpc/latest/userguide/VPC_Internet_Gateway.html) — 2-1의 1:1 NAT 동작과 퍼블릭 IP 요구사항
- [NAT gateways](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-gateway.html) — 공인/사설 연결 유형, 사설 NAT를 IGW로 보내면 드롭되는 동작
- [NAT gateway basics](https://docs.aws.amazon.com/vpc/latest/userguide/nat-gateway-basics.html) — 대역폭·pps·55,000 연결 한도, 보안 그룹 미지원
- [Troubleshoot NAT gateways](https://docs.aws.amazon.com/vpc/latest/userguide/nat-gateway-troubleshooting.html) — 함정 1·2·5의 증상과 원인
- [Compare NAT gateways and NAT instances](https://docs.aws.amazon.com/vpc/latest/userguide/vpc-nat-comparison.html) — RST/FIN 차이, 조각화·포트 포워딩 지원 여부
- [Egress-only internet gateways](https://docs.aws.amazon.com/vpc/latest/userguide/egress-only-internet-gateway.html) — 2-4
- [Regional NAT gateways](https://docs.aws.amazon.com/vpc/latest/userguide/nat-gateways-regional.html) — 6절
- [Block public access to VPCs and subnets](https://docs.aws.amazon.com/vpc/latest/userguide/security-vpc-bpa.html) — 함정 6
- `day04-vpc-subnet.md` — 서브넷을 왜 나누는가
- `day10-route-table.md` — 라우팅 테이블 우선순위, NAT 라우트를 잘못 넣어 생기는 루프
