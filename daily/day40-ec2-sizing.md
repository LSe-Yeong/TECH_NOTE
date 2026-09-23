# EC2 인스턴스 타입은 무엇을 기준으로 고르는가

> 이 문서가 답할 질문: **인스턴스 타입 목록에서 하나를 고를 때 무엇을 보고 고르며, 잘못 골랐다는 사실은 어떤 신호로 드러나는가?**
>
> 기준: AWS EC2 사용자 가이드 · EC2 Instance Types Guide · AWS Compute Optimizer 사용자 가이드 (2026년 9월 확인). 타입에 따라 달라지는 네트워크·스토리지 성능을 다루므로 `day16-igw-natgw.md`(NAT Gateway 대역폭)와 함께 읽으면 좋습니다.

## 1. 고르는 순간에 무엇이 정해지는가

EC2 인스턴스 타입은 **vCPU 개수·메모리 크기·네트워크 대역폭·EBS 대역폭을 한 번에 묶어 파는 단위**입니다. 넷을 따로 살 수 없습니다. 메모리만 두 배 필요해도 vCPU까지 같이 두 배가 되는 구조입니다.

> 문제는 이 선택이 **틀려도 즉시 알려주지 않는다**는 점입니다. 타입을 잘못 고른 서버는 기동에 실패하지 않습니다. 잘 돌다가 트래픽이 조금 늘었을 때, 또는 배포 직후 30분간만, 또는 매일 오후 2시에만 느려집니다. 그리고 CloudWatch의 `CPUUtilization`은 20%를 가리킵니다.
>
> 이 증상들의 정체는 대부분 **CPU 부족이 아니라 크레딧 소진**입니다. 작은 인스턴스는 CPU·네트워크·EBS 대역폭을 각각 별도의 크레딧 통으로 관리하고, 통이 비면 성능이 광고된 값이 아니라 베이스라인 값으로 떨어집니다. 타입 선택은 "얼마나 빠른가"를 고르는 일이 아니라 **"얼마나 오래 빠를 수 있는가"를 고르는 일**에 가깝습니다.

## 2. 이름이 이미 절반을 말해줍니다

`c7gn.xlarge`는 네 조각으로 읽습니다. 앞에서부터 **시리즈 → 세대 → 옵션 → 크기**입니다. ([인스턴스 타입 명명 규칙](https://docs.aws.amazon.com/ec2/latest/instancetypes/instance-type-names.html))

| 조각 | 예시 | 의미 |
|---|---|---|
| 시리즈 | `c` | 워크로드 성격. `m` 범용, `c` 컴퓨팅 최적화, `r` 메모리 최적화, `t` 버스터블, `i` 스토리지 최적화, `x` 메모리 집약 |
| 세대 | `7` | 숫자가 클수록 최신 하드웨어 |
| 옵션 | `gn` | 프로세서와 추가 능력 |
| 크기 | `xlarge` | `nano`부터 `metal`까지 |

옵션 문자는 알아두면 스펙 표를 뒤질 일이 줄어듭니다.

- **프로세서**: `a` AMD, `i` Intel, `g` AWS Graviton(Arm)
- **추가 능력**: `d` 인스턴스 스토어(로컬 NVMe), `n` 네트워크·EBS 최적화, `z` 고클럭, `e` 추가 메모리 또는 스토리지, `b` 블록 스토리지 최적화, `flex` Flex 인스턴스

즉 `c7gn`은 "컴퓨팅 최적화 7세대, Graviton, 네트워크 강화"입니다. `r6idn`은 "메모리 최적화 6세대, Intel, 로컬 NVMe, 네트워크 강화"입니다. 이름만 읽어도 후보를 절반으로 줄일 수 있습니다.

## 3. 고르는 순서 — 축을 하나씩 닫습니다

네 축을 동시에 비교하면 후보가 수백 개입니다. 순서대로 닫습니다.

### 3-1. 아키텍처: Graviton을 먼저 검토합니다

Graviton(Arm64)은 AWS가 같은 용도의 x86 인스턴스 대비 가격 대비 성능을 앞세우는 선택지입니다. 실제 차액은 리전과 타입마다 다르니 [온디맨드 요금표](https://aws.amazon.com/ec2/pricing/on-demand/)에서 직접 비교합니다. 걸림돌은 성능이 아니라 **빌드 산출물의 아키텍처**입니다.

- JVM·Python·Node.js처럼 인터프리터나 JIT 위에서 도는 코드는 **재컴파일 없이 동작합니다.**
- 문제는 네이티브 코드입니다. JNI 라이브러리, 네이티브 바이너리를 포함한 의존성, 그리고 무엇보다 **베이스 이미지가 amd64 전용인 Docker 이미지**가 걸립니다. ([AWS Graviton 기술 가이드](https://github.com/aws/aws-graviton-getting-started))

컨테이너를 쓴다면 판단 기준은 명확합니다. `docker buildx`로 멀티 아키텍처 이미지를 만들 수 있는가. 그게 되면 Graviton이 기본 후보입니다.

```bash
# 현재 이미지가 어떤 아키텍처를 지원하는지부터 확인합니다
docker buildx imagetools inspect public.ecr.aws/docker/library/eclipse-temurin:21-jre
```

### 3-2. 시리즈: 병목이 정합니다

vCPU 대비 메모리 비율이 시리즈를 가릅니다. 이 비율이 워크로드와 안 맞으면 한쪽이 남고 한쪽이 모자랍니다.

| 시리즈 | vCPU당 메모리 | 고르는 상황 |
|---|---|---|
| `c` | 2 GiB | 요청당 CPU를 쓰는 API 서버, 인코딩, 압축 |
| `m` | 4 GiB | 성격을 아직 모를 때의 기본값 |
| `r` | 8 GiB | 힙을 크게 잡는 JVM, 캐시 서버, 인메모리 집계 |

**측정 전이라면 `m`으로 시작합니다.** `c`로 시작하면 메모리가 먼저 마르고, `r`로 시작하면 CPU가 남는 값을 냅니다. `m`으로 하루 돌려보고 남는 쪽을 깎는 편이 빠릅니다.

### 3-3. 세대: 최신이 기본값입니다

같은 크기라면 최신 세대가 더 빠르고 대체로 시간당 단가도 낮거나 비슷합니다. M8i·M8i-flex는 2025년 8월 28일 GA했고, AWS는 M7i 대비 전반 성능 최대 20% 향상을 제시합니다. ([M8i 출시 공지](https://aws.amazon.com/about-aws/whats-new/2025/08/amazon-ec2-m8i-and-m8i-flex-instances-generally-available))

다만 **최신 세대는 모든 리전에 동시에 들어오지 않습니다.** 서울 리전에 없는 타입을 Terraform에 적어두면 apply가 실패합니다. 코드에 박기 전에 확인합니다.

```bash
# 이 리전에서 실제로 쓸 수 있는 타입만 나옵니다
aws ec2 describe-instance-type-offerings \
  --location-type region \
  --filters "Name=instance-type,Values=m8i.*" \
  --region ap-northeast-2 \
  --query "InstanceTypeOfferings[].InstanceType" --output text
```

### 3-4. 크기: 작은 인스턴스에는 성능 상한이 따로 있습니다

여기서 대부분의 사고가 납니다. 크기를 줄이면 vCPU와 메모리만 줄어드는 게 아니라 **네트워크와 EBS 성능이 "지속 가능한 값"과 "잠깐 낼 수 있는 값"으로 쪼개집니다.**

## 4. 세 개의 크레딧 통

작은 인스턴스는 CPU·네트워크·EBS를 각각 독립된 버스트 예산으로 굴립니다. 셋은 서로 무관하게 바닥납니다.

### 4-1. CPU 크레딧 — T 계열

T 계열은 **베이스라인 CPU 사용률**을 정해두고, 그 아래로 쓰면 크레딧을 쌓고 그 위로 쓰면 크레딧을 씁니다. 1 크레딧은 `1 vCPU × 100% × 1분`입니다. ([버스터블 인스턴스 핵심 개념](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-credits-baseline-concepts.html))

| 타입 | 시간당 크레딧 | 누적 한도 | vCPU | vCPU당 베이스라인 |
|---|---:|---:|---:|---:|
| `t3.nano` | 6 | 144 | 2 | 5% |
| `t3.micro` | 12 | 288 | 2 | 10% |
| `t3.small` | 24 | 576 | 2 | 20% |
| `t3.medium` | 24 | 576 | 2 | 20% |
| `t3.large` | 36 | 864 | 2 | 30% |
| `t3.xlarge` | 96 | 2304 | 4 | 40% |
| `t3.2xlarge` | 192 | 4608 | 8 | 40% |

읽는 법이 중요합니다. `t3.large`의 베이스라인 30%는 **CloudWatch의 `CPUUtilization`이 30%로 보이는 지점**입니다. 즉 지표가 30%를 넘어 계속 머무는 순간부터 크레딧이 줄고 있습니다. 누적 한도는 전부 24시간치 발행량과 같습니다 — `t3.nano`면 `24 × 6 = 144`입니다. 하루 이상 쉬게 해도 예산은 더 늘지 않습니다.

두 가지를 더 알아둡니다.

- **T3·T3a·T4g·T8i는 `unlimited`가 기본값입니다.** 크레딧이 떨어져도 느려지지 않고, 24시간 롤링 평균이 베이스라인을 넘으면 vCPU-시간 단위로 추가 과금됩니다. 성능 저하 대신 청구서가 움직이는 구조입니다.
- **정지해도 크레딧이 7일간 유지됩니다**(T3·T3a·T4g·T8i). 반면 구세대 T2는 정지하는 순간 전부 사라집니다.

### 4-2. 네트워크 I/O 크레딧

스펙에 `Up to 10 Gigabit`이라 적힌 값은 **상한이지 보장값이 아닙니다.** 보통 16 vCPU 이하(`4xlarge` 이하)가 이 "up to" 표기를 받고, 별도의 베이스라인을 갖습니다. ([EC2 인스턴스 네트워크 대역폭](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-network-bandwidth.html))

AWS 문서의 C5 예시가 격차를 그대로 보여줍니다.

| 타입 | 표기 성능 | 베이스라인 |
|---|---|---:|
| `c5.large` | Up to 10 Gigabit | 0.75 Gbps |
| `c5.xlarge` | Up to 10 Gigabit | 1.25 Gbps |
| `c5.4xlarge` | Up to 10 Gigabit | 5.0 Gbps |
| `c5.9xlarge` | 12 Gigabit | 12.0 Gbps |

`c5.large`의 실제 지속 대역폭은 표기값의 13분의 1입니다. 버스트 지속 시간은 인스턴스 크기에 따라 **보통 5분에서 60분**이고, 크레딧이 마르면 베이스라인으로 내려옵니다. 인바운드와 아웃바운드는 크레딧 통이 분리돼 있으며, 버스트는 공유 자원이라 **크레딧이 있어도 best effort**입니다.

여기에 플로우 단위 상한이 겹칩니다. 클러스터 배치 그룹 밖에서 **단일 플로우(5-튜플)는 5 Gbps가 상한**입니다. 25 Gbps 인스턴스를 띄워도 커넥션 하나로는 5 Gbps를 못 넘습니다. 큰 파일을 한 커넥션으로 옮기는 설계가 느린 이유가 이것입니다. 또 32 vCPU 미만 인스턴스는 인터넷 게이트웨이를 지나는 트래픽이 5 Gbps로 제한됩니다.

콘솔에는 베이스라인이 표시되지 않습니다. CLI로 봐야 합니다.

```bash
aws ec2 describe-instance-types \
  --filters "Name=instance-type,Values=m7i.*" \
  --query "InstanceTypes[].[InstanceType, NetworkInfo.NetworkPerformance, NetworkInfo.NetworkCards[0].BaselineBandwidthInGbps] | sort_by(@,&[2])" \
  --output table
```

### 4-3. EBS 대역폭 버스트

세 번째 통입니다. `m5.large`의 EBS 베이스라인은 650 Mbps·3,600 IOPS(16 KiB 기준)이고 최대는 4,750 Mbps·18,750 IOPS입니다. 이 최대치는 **24시간에 최소 한 번, 30분간** 유지할 수 있고 그 뒤 베이스라인으로 돌아옵니다. `4xlarge` 이상은 버스트 제약 없이 표기 성능을 지속합니다. ([EBS 최적화 인스턴스](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ebs-optimized.html))

그리고 실제 성능은 **인스턴스 한도와 볼륨 성능 중 작은 쪽**입니다. gp3 볼륨에 IOPS를 아무리 올려도 `large` 인스턴스에 붙이면 인스턴스 한도에서 잘립니다. 반대도 마찬가지입니다.

## 5. T·Flex·M을 어떻게 가르는가

셋 다 "평소엔 놀고 가끔 바쁜" 워크로드를 노립니다. 성격이 다릅니다.

| | T 계열 | Flex(`m7i-flex`·`m8i-flex`) | 표준 M 계열 |
|---|---|---|---|
| 베이스라인 | 사이즈별 5~40% | **40%** | 없음(항상 전부) |
| 버스트 방식 | 크레딧 잔량만큼 | 24시간 중 95% 시간 동안 100%까지 | 해당 없음 |
| 초과 시 | `unlimited`면 추가 과금, `standard`면 감속 | 지속 초과 시 최대 버스트가 점진적으로 하락 | 해당 없음 |
| 사이즈 | `nano`~`2xlarge` | `large`~`8xlarge`(m7i-flex) | 전 사이즈 |

Flex는 AWS 발표 기준 m7i 대비 **5% 낮은 가격**으로 제공됩니다. ([M7i·M7i-flex 출시 글](https://aws.amazon.com/blogs/aws/new-seventh-generation-general-purpose-amazon-ec2-instances-m7i-flex-and-m7i/))

실무 판단은 이렇게 갈립니다.

- **T 계열**: 하루 평균 CPU가 베이스라인보다 확실히 낮은 것 — 사내 도구, 개발·스테이징 환경, 배치 스케줄러. `nano`~`micro`가 필요한 아주 작은 워크로드는 T 말고 선택지가 없습니다.
- **Flex**: 평균은 낮지만 **바닥을 예측하기 어려운** 프로덕션 API 서버. 크레딧 잔량을 관리할 필요가 없다는 점이 T와의 결정적 차이입니다.
- **표준 M/C/R**: 부하가 꾸준하거나, 성능이 튀는 것 자체가 장애인 것 — 오후 내내 도는 배치, 실시간 처리.

**프로덕션 DB나 상시 부하 서버에 T 계열을 쓰지 않습니다.** 크레딧이 마르는 시점이 곧 트래픽이 가장 많은 시점이기 때문입니다.

## 6. 예제 — 주문 API 서버를 올린다면

가정은 이렇습니다. Spring Boot 애플리케이션, 힙 4 GB, 평시 초당 100건, 프로모션 때 초당 400건, RDS를 따로 쓰고 로컬 디스크는 로그만 씁니다.

### 6-1. 흔한 선택 ❌

```
t3.medium 2대
```

세 군데가 어긋납니다.

1. **메모리**: `t3.medium`은 4 GiB입니다. 힙 4 GB를 잡으면 메타스페이스·스레드 스택·네이티브 버퍼가 들어갈 자리가 없습니다(`day07-jvm-memory.md`). OOM Killer가 프로세스를 지우고, 로그에는 아무것도 안 남습니다(7-3).
2. **CPU**: 베이스라인이 vCPU당 20%입니다. 프로모션 30분이면 누적 크레딧 576개를 다 태우고, 그 뒤로는 `unlimited` 과금이 붙거나 감속합니다.
3. **대수**: 2대지만 AZ 배치를 명시하지 않으면 같은 AZ에 몰릴 수 있습니다.

### 6-2. 고쳐 본 선택 ✔️

```
m8g.large 2대 (2 AZ에 분산), Auto Scaling 최대 4대
```

근거를 축별로 답니다.

- **아키텍처**: JVM이므로 Graviton에서 재컴파일이 필요 없습니다(3-1). 컨테이너를 쓴다면 이미지가 arm64를 포함하는지만 확인합니다.
- **시리즈**: 힙 4 GB에 여유를 두려면 vCPU당 4 GiB인 `m`이 맞습니다. `large`는 8 GiB입니다.
- **버스트**: 표준 M 계열이라 CPU 크레딧 개념 자체가 없습니다. 프로모션이 몇 시간 이어져도 성능이 계단식으로 떨어지지 않습니다.
- **스파이크 대응**: 크기를 키워 흡수하지 않고 대수로 흡수합니다. 4배 트래픽을 한 대로 받으려면 `2xlarge`가 필요하지만, 그 용량은 평시 내내 놀고 있습니다.

남는 리스크도 분명합니다. `m8g.large`는 `4xlarge` 미만이라 **EBS·네트워크 버스트 제약은 그대로 받습니다**(4-2, 4-3). 이 서버는 RDS를 쓰고 로컬 I/O가 로그뿐이라 문제되지 않지만, 같은 크기로 파일 업로드를 중계한다면 다시 계산해야 합니다.

## 7. 함정

### 7-1. CPU 사용률이 낮은데 응답이 느립니다

- **증상**: CloudWatch `CPUUtilization`은 25%인데 p99 지연이 튀고, 재시작하면 잠시 괜찮아집니다.
- **원인**: `t3.large`의 베이스라인이 30%입니다. 25%는 "한가한 상태"가 아니라 베이스라인 바로 아래이며, 순간 스파이크마다 크레딧을 갉고 있습니다. 재시작 후 잠깐 괜찮아지는 건 `unlimited` 모드에서 잉여 크레딧으로 버티기 때문입니다.
- **해법**: `CPUCreditBalance`와 `CPUSurplusCreditBalance`를 봅니다. 잔액이 0에 붙어 있으면 타입 선택이 틀린 것입니다. 지표 자체가 없으면 T 계열이 아니므로 다른 병목을 봐야 합니다.

```bash
aws cloudwatch get-metric-statistics \
  --namespace AWS/EC2 --metric-name CPUCreditBalance \
  --dimensions Name=InstanceId,Value=i-0123456789abcdef0 \
  --start-time 2026-09-22T00:00:00Z --end-time 2026-09-23T00:00:00Z \
  --period 300 --statistics Minimum --output table
```

### 7-2. 요금이 조용히 올라갑니다

- **증상**: 인스턴스를 늘린 적이 없는데 EC2 비용이 매달 오릅니다.
- **원인**: `unlimited` 모드는 24시간 평균이 베이스라인을 넘으면 **성능을 떨어뜨리는 대신 과금합니다.** 성능 저하라는 알림이 없으니 청구서를 열기 전까지 아무도 모릅니다. 부하가 꾸준히 늘면 T 계열이 같은 크기의 M 계열보다 비싸지는 구간이 생깁니다.
- **해법**: 개발·스테이징처럼 느려져도 되는 환경은 `standard`로 내려 상한을 강제합니다. 프로덕션이라면 `unlimited`를 유지하되 Flex나 M 계열로 옮기는 것이 정답인지 계산합니다.

```bash
aws ec2 modify-instance-credit-specification \
  --instance-credit-specification "InstanceId=i-0123456789abcdef0,CpuCredits=standard"
```

### 7-3. 메모리가 모자란 건 지표에 안 보입니다

- **증상**: 프로세스가 로그 한 줄 없이 사라집니다. 애플리케이션 로그에는 아무것도 남지 않습니다.
- **원인**: EC2 기본 CloudWatch 지표에 **메모리 사용률이 없습니다.** 하이퍼바이저가 게스트 OS 내부를 못 보기 때문입니다. Linux OOM Killer가 프로세스를 죽여도 `dmesg`에만 남습니다. 결국 메모리 부족을 CPU 지표로 진단하려다 실패합니다.
- **해법**: CloudWatch 에이전트로 `mem_used_percent`를 `CWAgent` 네임스페이스에 올리고, `InstanceId` 디멘전을 반드시 포함시킵니다. 디멘전 이름을 바꾸면 Compute Optimizer가 데이터를 못 읽습니다. ([Compute Optimizer EC2 지표](https://docs.aws.amazon.com/compute-optimizer/latest/ug/ec2-metrics-analyzed.html))

### 7-4. 크게 한 대 vs 작게 여러 대

- **증상**: `m7i.4xlarge` 한 대로 올렸더니 평균 응답은 좋은데 배포할 때마다 전체가 흔들립니다.
- **원인**: 한 대짜리 구성은 AZ 장애·재기동·배포가 전부 100% 손실입니다. 반대로 `large` 여러 대로 흩으면 대당 EBS·네트워크 베이스라인이 낮아 I/O가 많은 워크로드에서 총합이 기대보다 안 나옵니다.
- **해법**: 같은 총 vCPU라면 **최소 2 AZ에 걸치는 구성**을 우선하고, 그 제약 안에서 대당 크기를 정합니다. I/O가 병목이면 대수를 늘리는 대신 `4xlarge` 이상으로 올려 버스트 제약 자체를 없애는 쪽이 단순합니다.

### 7-5. 타입을 바꾸면 할인 약정이 어긋납니다

- **증상**: 최적화한다고 타입을 바꿨는데 비용이 오히려 늘었습니다.
- **원인**: Savings Plans와 Reserved Instance는 적용 범위가 다릅니다. 특히 아키텍처를 x86에서 Graviton으로 바꾸면 기존 약정이 그대로 따라가지 않을 수 있습니다. <!-- TODO: 확인 필요 — Compute Savings Plans의 아키텍처 간 적용 범위는 계약 종류·시점에 따라 달라 공식 약관으로 재확인 후 단정할 것 -->
- **해법**: 타입 변경 전에 Cost Explorer에서 현재 약정 커버리지를 먼저 확인합니다. 약정이 걸린 자원은 약정 만료 시점에 맞춰 교체 계획을 세웁니다.

## 8. 잘못 골랐는지 확인하는 절차

처음 고른 타입이 맞을 확률은 낮습니다. **바꿀 수 있게 해두는 것**이 잘 고르는 것보다 중요합니다.

1. **측정 가능 상태를 먼저 만듭니다.** CloudWatch 에이전트로 메모리를 올리고, T 계열이면 크레딧 잔량 알람을 겁니다.
2. **최소 30시간을 모읍니다.** Compute Optimizer는 최근 14일 안에 **최소 30시간**의 CloudWatch 지표를 요구합니다. 향상된 인프라 지표를 켜면 최근 93일 기준으로 봅니다. 비용 계산을 위해 Cost Explorer도 켜야 합니다. ([Compute Optimizer 리소스 요구사항](https://docs.aws.amazon.com/compute-optimizer/latest/ug/requirements.html))
3. **권고를 그대로 믿지 않습니다.** 메모리 지표를 안 올렸다면 Compute Optimizer는 CPU·네트워크·디스크만 보고 판단합니다. 메모리가 병목인 서버에 "과다 프로비저닝"이라는 결론이 나올 수 있습니다.
4. **업무 주기보다 긴 창으로 봅니다.** 월말 정산 배치가 있는 시스템을 14일 지표로 줄이면 월말에 터집니다.

```bash
aws compute-optimizer get-ec2-instance-recommendations \
  --instance-arns arn:aws:ec2:ap-northeast-2:111122223333:instance/i-0123456789abcdef0 \
  --query "instanceRecommendations[].[finding, currentInstanceType, recommendationOptions[0].instanceType]" \
  --output table
```

## 9. 참고자료

- [Amazon EC2 인스턴스 타입 명명 규칙](https://docs.aws.amazon.com/ec2/latest/instancetypes/instance-type-names.html)
- [버스터블 성능 인스턴스의 핵심 개념](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-credits-baseline-concepts.html)
- [Amazon EC2 인스턴스 네트워크 대역폭](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-network-bandwidth.html)
- [Amazon EBS 최적화 인스턴스](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ebs-optimized.html)
- [AWS Compute Optimizer 리소스 요구사항](https://docs.aws.amazon.com/compute-optimizer/latest/ug/requirements.html)
- [AWS Graviton 기술 가이드](https://github.com/aws/aws-graviton-getting-started)
- 관련 문서: `day16-igw-natgw.md`(NAT Gateway 대역폭과 요금), `day30-application-healthcheck.md`(성능 저하를 감지하는 지점)
