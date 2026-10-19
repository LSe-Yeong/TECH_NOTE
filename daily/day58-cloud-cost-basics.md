# 청구서는 왜 견적보다 많이 나오는가

> 이 문서가 답할 질문: **Pricing Calculator로 뽑은 견적과 실제 청구서가 왜 어긋나는가, 그리고 그 차액이 어디서 왔는지 어떻게 찾아내는가?**
>
> 기준: AWS 공식 요금 페이지·문서 (2026년 10월 확인), 단가는 별도 표기가 없으면 **US East 리전** 기준입니다. 리전마다 다릅니다. 환경 분리와 비용의 관계는 `day52-env-separation.md`, 로그 볼륨은 `day48-log-level.md`·`day36-log-design.md`, 인스턴스 타입 선택은 `day40-ec2-sizing.md`와 이어집니다.

## 1. 견적과 청구서는 서로 다른 것을 계산합니다

요금 예측은 보통 이렇게 합니다. EC2 `t3.medium` 두 대, RDS `db.t3.medium` 한 대, S3 100GB. 계산기에 넣으면 월 $150쯤 나옵니다. 그런데 다음 달 청구서는 $400입니다.

계산 실수가 아닙니다. 둘이 세는 대상이 다릅니다.

> 계산기는 **내가 적어 넣은 리소스**를 계산합니다. 청구서는 **실제로 켜져 있던 시간, 실제로 움직인 바이트, 실제로 날아간 요청 건수**를 계산합니다. 이 둘의 간격에 들어가는 것들은 아키텍처 다이어그램에 그려지지 않는 것들입니다 — NAT Gateway, 퍼블릭 IP, 지우지 않은 EBS 볼륨, DEBUG로 켜둔 로그, AZ를 넘나드는 내부 트래픽.
>
> 더 나쁜 건 이 항목들이 **트래픽에 비례해서 조용히 커진다**는 점입니다. 터지지 않고, 느려지지도 않고, 알림도 오지 않습니다. 다음 달 1일에 숫자로만 나타납니다.

그래서 이 문서는 "비용을 줄이는 팁" 목록이 아닙니다. **청구서를 구성하는 축이 무엇이고, 그중 무엇이 견적에서 빠지는가**를 봅니다. 축을 알면 다음 달 숫자를 보기 전에 짚을 수 있습니다.

## 2. 요금이 붙는 네 개의 축

클라우드 요금은 리소스 단가의 합이 아닙니다. 네 개의 축에서 각각 계산되고, 그 합이 청구서입니다.

| 축 | 과금 기준 | 견적에서 빠지는 이유 |
|---|---|---|
| **시간** | 리소스가 존재한 시간 (사용량 무관) | 다이어그램에 안 그리는 리소스를 계산기에 안 넣습니다 |
| **용량** | 프로비저닝한 양 (쓴 양 아님) | "100GB 쓸 거니까 100GB"로 적지만, 과거에 만든 것들이 남아 있습니다 |
| **이동** | 전송한 GB, 방향별로 | 내부 통신이 과금 대상인 줄 모릅니다 |
| **건수** | API 요청·로그 라인 | 트래픽에 선형 비례해서 커집니다 |

견적이 주로 맞히는 건 첫 두 축의 일부뿐입니다. 아래 네 절에서 축마다 실제로 걸리는 지점을 봅니다.

## 3. 축 1 — 사용량이 0이어도 켜져 있으면 돈이 나갑니다

가장 흔한 간격입니다. "요청이 없으면 돈도 안 나간다"는 감각은 서버리스에만 적용됩니다.

**NAT Gateway.** 프라이빗 서브넷을 만들면 거의 자동으로 따라오는 리소스입니다. US East (Ohio) 기준 시간당 $0.045 + 처리한 데이터 GB당 $0.045이고, 공식 요금 페이지는 **"사용한 부분 NAT Gateway-시간은 전체 시간으로 과금"**된다고 못을 박습니다. ([VPC 요금](https://aws.amazon.com/vpc/pricing/)) 트래픽이 한 바이트도 없어도 730시간 × $0.045 = 월 약 $32.85입니다. AZ마다 하나씩 두는 것이 권장 구성이므로, AZ 3개면 아무것도 안 해도 월 $98입니다.

**퍼블릭 IPv4 주소.** 2024년 2월 1일부터 **서비스에 붙어 있든 아니든 모든 퍼블릭 IPv4 주소가 시간당 $0.005**입니다. 그 전까지 VPC 안의 리소스에 붙은 주소는 무료였습니다. ([AWS News Blog](https://aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-public-ip-insights/)) 한 개는 월 $3.65이지만, EC2 10대 + ALB + NAT Gateway + RDS 퍼블릭 액세스까지 세어 보면 개수가 생각보다 큽니다.

**EBS 볼륨.** 인스턴스가 멈춰 있어도 볼륨은 과금됩니다. 공식 페이지는 **"릴리스할 때까지"** 프로비저닝한 GB 기준으로 과금한다고 적습니다 — `gp3` $0.08/GB-월, `gp2` $0.10/GB-월. ([EBS 요금](https://aws.amazon.com/ebs/pricing/))

**중지한 RDS.** 비용을 아끼려고 dev DB를 중지했는데 요금이 크게 안 줄어듭니다. 문서가 명시합니다 — 중지 중에는 DB 인스턴스 시간은 과금되지 않지만 **프로비저닝 스토리지(Provisioned IOPS 포함), 백업 스토리지, 퍼블릭 IPv4 주소는 계속 과금**됩니다. 그리고 결정적으로, **7일 연속 중지되면 RDS가 자동으로 다시 시작합니다.** ([RDS 중지](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_StopInstance.html))

> 이게 "분명히 껐는데 요금이 그대로"의 가장 흔한 정체입니다. 금요일에 끄고 간 dev DB가 다음 주 금요일에 혼자 켜져서, 그 뒤로 한 달간 돕니다. 중지는 비용 대책이 아니라 임시 조치입니다. 장기간 안 쓸 DB는 스냅샷을 뜨고 삭제하거나, 스케줄러로 매일 끄는 쪽이 맞습니다.

## 4. 축 2 — 데이터는 움직일 때마다 요금이 붙습니다

인바운드는 무료라서 "트래픽은 공짜"라는 인상이 생기지만, 과금되는 건 주로 **나가는 방향과 경계를 넘는 방향**입니다.

기준선 세 개만 기억하면 됩니다.

1. **같은 AZ 안, 프라이빗 IP** → 무료. AWS 문서가 "동일 가용 영역 내 데이터 전송은 무료"라고 명시합니다. ([데이터 전송 비용 개요](https://aws.amazon.com/blogs/architecture/overview-of-data-transfer-costs-for-common-architectures/))
2. **같은 리전, AZ를 넘음** → **방향마다 GB당 $0.01.** 왕복이면 $0.02입니다. ([ELB 데이터 전송 비용](https://aws.amazon.com/blogs/networking-and-content-delivery/exploring-data-transfer-costs-for-classic-and-application-load-balancers/))
3. **인터넷으로 나감** → 월 100GB까지 무료(서비스·리전 합산), 이후 리전별 단가. ([EC2 On-Demand 요금](https://aws.amazon.com/ec2/pricing/on-demand/))

여기서 실무가 자주 밟는 두 지점이 있습니다.

### 4-1. 같은 VPC에서 인터넷향 로드밸런서를 때리는 구성

내부 서비스끼리 호출하면서 주소를 인터넷향 ALB의 DNS로 적어둔 경우입니다. 이 트래픽은 **인터넷 게이트웨이를 왕복하면서 방향마다 GB당 $0.01이 추가로 붙습니다.** AWS 블로그가 직접 적고, 같은 VPC 클라이언트에는 내부(internal) 로드밸런서를 쓰라고 권합니다. ([같은 글](https://aws.amazon.com/blogs/networking-and-content-delivery/exploring-data-transfer-costs-for-classic-and-application-load-balancers/))

코드는 멀쩡하고 응답도 정상입니다. 지연만 조금 늘고 요금만 붙습니다.

### 4-2. 프라이빗 서브넷에서 S3를 호출하는 구성

프라이빗 서브넷의 애플리케이션이 S3에 파일을 올립니다. 기본 라우팅이면 이 트래픽은 NAT Gateway를 타고, **처리량 GB당 $0.045**가 붙습니다. 리전 내 S3 호출인데 NAT 요금을 내는 겁니다.

해법이 명확합니다. S3와 DynamoDB용 **Gateway 타입 VPC 엔드포인트는 시간당 요금도, 데이터 처리 요금도 없습니다.** ([VPC 요금](https://aws.amazon.com/vpc/pricing/))

```hcl
# ✔️ 라우팅 테이블에 S3 게이트웨이 엔드포인트를 붙여 NAT를 우회한다
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.ap-northeast-2.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
}
```

엔드포인트를 만들어도 **프라이빗 서브넷의 라우팅 테이블에 연결하지 않으면 트래픽은 계속 NAT로 갑니다.** 생성과 연결은 별개입니다(`day10-route-table.md`).

## 5. 축 3 — 로그와 요청은 건수로 계산됩니다

이 축은 트래픽에 선형으로 비례합니다. 그래서 서비스가 성장하면 가장 빠르게 커집니다.

CloudWatch Logs 수집은 **GB당 $0.50**, 보관은 **GB-월당 $0.03**이고, 무료 한도는 수집·보관·Logs Insights 스캔을 **합쳐서** 월 5GB입니다. ([CloudWatch 요금](https://aws.amazon.com/cloudwatch/pricing/))

$0.50이라는 숫자는 작아 보입니다. 직접 곱해 보면 인상이 달라집니다.

```
요청 1건당 로그 10KB (요청/응답/SQL/스택트레이스 합산)
일 300만 요청 → 하루 약 30GB → 한 달 약 900GB
900GB × $0.50 = 월 약 $450  (수집 요금만. 보관·조회는 별도)
```

요청당 10KB는 과장이 아닙니다. 요청 바디와 응답 바디를 통째로 찍고, JPA SQL 로그를 켜두고, 예외 스택트레이스가 섞이면 금방 넘습니다.

### 5-1. 로그 요금을 만드는 코드

```xml
<!-- ❌ logback-spring.xml — 프로덕션 프로필에서 DEBUG가 살아 있다 -->
<configuration>
  <springProfile name="prod">
    <logger name="com.example.order" level="DEBUG"/>
    <logger name="org.hibernate.SQL" level="DEBUG"/>
    <logger name="org.hibernate.orm.jdbc.bind" level="TRACE"/>
    <root level="DEBUG">
      <appender-ref ref="CONSOLE"/>
    </root>
  </springProfile>
</configuration>
```

장애 대응 중에 DEBUG로 올리고 되돌리지 않는 패턴이 가장 흔합니다. 터지지 않으므로 아무도 발견하지 못합니다.

```xml
<!-- ✔️ 프로덕션은 INFO. 조사용 상세 로그는 런타임에 켜고 끈다 -->
<configuration>
  <springProfile name="prod">
    <logger name="com.example.order" level="INFO"/>
    <root level="WARN">
      <appender-ref ref="JSON"/>
    </root>
  </springProfile>
</configuration>
```

Spring Boot Actuator의 `loggers` 엔드포인트를 열어두면 재배포 없이 특정 패키지만 한시적으로 DEBUG로 올릴 수 있습니다. 설정 파일에 DEBUG를 박아두는 것보다 훨씬 안전합니다. 로그 레벨 기준은 `day48-log-level.md`를 참고합니다.

### 5-2. 보관 기간을 설정하지 않으면 무기한입니다

로그 그룹의 기본 보관 정책은 "만료 없음"입니다. 3년 전 로그가 계속 $0.03/GB-월을 먹습니다.

```hcl
resource "aws_cloudwatch_log_group" "order_api" {
  name              = "/ecs/order-api"
  retention_in_days = 30
}
```

애플리케이션 로그는 30~90일, 감사 로그는 규정이 요구하는 기간으로 두고, 장기 보관이 필요하면 S3로 내보내는 쪽이 저렴합니다. 그리고 "건수를 세기 위한 로그"는 로그가 아니라 메트릭으로 내보내는 게 맞습니다(`day54-golden-signals.md`).

## 6. 축 4 — 지웠다고 생각한 것이 남아 있습니다

청구서에서 가장 설명하기 어려운 항목들입니다. 쓰는 사람이 없는데 과금됩니다.

- **연결되지 않은 EBS 볼륨** — 인스턴스를 종료할 때 `DeleteOnTermination`이 `false`인 추가 볼륨은 남습니다. 삭제할 때까지 과금됩니다.
- **쌓인 스냅샷** — 표준 티어 **$0.05/GB-월**. 자동 스냅샷에 수명주기 정책이 없으면 선형으로 늘어납니다. ([EBS 요금](https://aws.amazon.com/ebs/pricing/))
- **완료되지 않은 S3 멀티파트 업로드** — 업로드가 중간에 실패하면 올라간 파트가 버킷에 남습니다. 콘솔의 객체 목록에는 보이지 않는데 스토리지 요금은 나갑니다. AWS는 **`AbortIncompleteMultipartUpload` 수명주기 규칙**을 권장합니다. ([S3 문서](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpu-abort-incomplete-mpu-lifecycle-config.html))

```json
{
  "Rules": [
    {
      "ID": "abort-incomplete-mpu",
      "Status": "Enabled",
      "Filter": { "Prefix": "" },
      "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 7 }
    }
  ]
}
```

### 6-1. 스토리지 클래스 전환이 오히려 비싸지는 경우

"S3 요금을 줄이려면 수명주기로 IA나 Glacier로 보내라"는 조언에는 조건이 붙습니다. 저가 클래스에는 **최소 보관 기간**과 **최소 과금 객체 크기**가 있습니다.

| 클래스 | 최소 보관 기간 | 최소 과금 크기 |
|---|---|---|
| Standard-IA | 30일 | 128KB |
| Glacier Instant Retrieval | 90일 | 128KB |
| Glacier Flexible Retrieval | 90일 | — |
| Glacier Deep Archive | 180일 | — |

([S3 요금](https://aws.amazon.com/s3/pricing/))

그래서 **수명이 짧은 객체를 IA로 보내면 손해**입니다. 7일 뒤 지울 썸네일을 30일 최소 기간이 걸린 클래스로 옮기면 남은 23일을 더 냅니다. 그리고 **10KB 파일 100만 개**를 128KB 최소 과금 크기가 걸린 클래스로 옮기면, 실제 10GB를 128GB로 계산합니다. 여기에 전환 요청 요금까지 붙습니다.

판단 기준 한 줄입니다. **객체가 최소 보관 기간보다 오래 살고, 최소 과금 크기보다 큰가.** 둘 중 하나라도 아니면 Standard에 두는 게 쌉니다.

## 7. 견적을 다시 만드는 법

다음 견적에서 같은 실수를 안 하려면, 리소스 목록이 아니라 **네 축을 채우는 방식**으로 적습니다. 서비스 요금 페이지도 이 순서로 읽으면 빠뜨리지 않습니다.

| 축 | 요금 페이지에서 찾는 단어 | 견적에 적을 것 |
|---|---|---|
| 시간 | `per hour`, `per hour or partial hour` | 리소스 개수 × 730시간. **AZ 수를 곱하는 것을 잊지 않습니다** |
| 용량 | `provisioned`, `per GB-month` | 쓸 양이 아니라 **프로비저닝할 양** |
| 이동 | `data processing`, `data transfer`, `per GB` | 방향별로. AZ를 넘는지 여부를 먼저 정합니다 |
| 건수 | `per 1,000 requests`, `per GB ingested` | 요청 수 × 요청당 바이트 |

그리고 세 가지를 반드시 따로 적습니다. 견적에서 가장 자주 빠지는 항목들입니다.

1. **아키텍처 다이어그램에 없는 리소스** — NAT Gateway, 퍼블릭 IP, 로드밸런서, 엔드포인트
2. **로그와 메트릭** — 요청당 로그 크기를 모르면 스테이징에서 한 번 재봅니다
3. **환경 개수** — dev·staging·prod가 각자 NAT Gateway와 RDS를 가지면 고정비는 3배입니다(`day52-env-separation.md`)

마지막으로, 견적은 **최소 두 개**를 만듭니다. 기준 트래픽과 기준의 5배입니다. 두 숫자의 차이가 곧 "트래픽에 비례하는 비용"이고, 그게 이 서비스의 단위 경제입니다. 고정비만 적힌 견적은 성장했을 때 아무것도 알려주지 않습니다.

## 8. 차액을 찾아내는 절차

"요금이 많이 나왔다"에서 원인까지 가는 순서입니다. 추측부터 하면 틀립니다.

1. **Cost Explorer를 서비스별로 봅니다.** 상위 3개가 전체의 대부분입니다.
2. **그 서비스를 Usage Type으로 그룹화합니다.** 이 단계가 핵심입니다. `NatGateway-Bytes`, `DataTransfer-Regional-Bytes`, `TimedStorage-ByteHrs` 처럼 **어느 축에서 돈이 나갔는지**가 여기서 드러납니다. §2의 네 축으로 바로 매핑됩니다.
3. **그 축의 발생 지점을 좁힙니다.** 전송량이면 VPC Flow Logs로 어느 ENI 쌍인지, 로그면 어느 로그 그룹인지.
4. **태그로 책임 주체를 가릅니다.** 여기가 막히는 지점입니다 ↓

⚠️ 비용 할당 태그는 **소급 적용되지 않습니다.** 공식 문서가 명시합니다 — **"태그가 생성되기 전에 만들어진 리소스에는 태그가 적용되지 않습니다."** 활성화도 별도 작업이고, 관리 계정에서만 가능합니다. ([비용 할당 태그](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/custom-tags.html)) 요금이 터진 다음에 태그를 붙여도 지난달 청구서는 가를 수 없습니다. 태그 전략은 리소스를 만들 때 정해야 합니다. 이게 안 되면 환경·팀별 비용은 **계정 단위로 가르는 게 더 확실합니다**(`day52-env-separation.md`).

5. **Budgets로 다음번을 막습니다.** 단, 한계를 알고 써야 합니다. 예산 정보는 **하루 최대 3회 갱신되고, 갱신 간격은 보통 8~12시간**입니다. 문서도 과금 시점과 알림 시점 사이에 지연이 있다고 적습니다. ([AWS Budgets](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html)) 즉 Budgets는 **사고를 막는 장치가 아니라 늦게 알려주는 장치**입니다. 실제로 멈추려면 예산 작업(budget actions)으로 추가 프로비저닝을 거부하는 IAM 정책을 붙여야 합니다.

## 9. 함정

**중지했는데 요금이 줄지 않습니다**
- **증상**: dev RDS를 중지했는데 다음 달 RDS 비용이 거의 그대로입니다. 콘솔을 보니 인스턴스가 `available` 상태입니다.
- **원인**: 중지 중에도 스토리지·백업·퍼블릭 IPv4는 과금되고, 7일이 지나면 RDS가 자동으로 재시작합니다(§3).
- **해법**: 장기 미사용이면 스냅샷을 남기고 삭제합니다. 주기적으로 꺼야 한다면 EventBridge 스케줄로 매일 중지를 다시 거는 자동화를 둡니다. 퍼블릭 액세스는 끕니다.

**프라이빗 서브넷을 만든 뒤 요금이 올랐습니다**
- **증상**: 보안을 위해 애플리케이션을 프라이빗 서브넷으로 옮겼더니 월 비용이 수십 달러 늘었고, 청구서에 `NatGateway-Hours`와 `NatGateway-Bytes`가 보입니다.
- **원인**: AZ마다 NAT Gateway를 두면 고정비가 AZ 수만큼 붙고(§3), S3·ECR·CloudWatch 호출까지 전부 NAT를 타면서 GB당 $0.045가 추가됩니다.
- **해법**: S3·DynamoDB는 Gateway 엔드포인트로 뺍니다(무료). ECR·CloudWatch Logs 같은 것은 인터페이스 엔드포인트가 있지만 **이쪽은 시간당·GB당 요금이 있으므로** NAT 처리량과 비교해서 결정합니다. dev 환경은 NAT를 AZ 하나만 두고 가용성을 포기하는 것도 합리적인 선택입니다.

**트래픽이 두 배인데 전송 요금은 네 배입니다**
- **증상**: 요청 수는 2배인데 `DataTransfer-Regional-Bytes`가 4배가 됐습니다.
- **원인**: 스케일아웃으로 인스턴스가 여러 AZ에 퍼지면서, 전에는 같은 AZ 안에서 끝났던 호출이 AZ를 넘기 시작했습니다. AZ를 넘는 트래픽은 **방향마다** 과금됩니다(§4).
- **해법**: 트래픽이 큰 구간(애플리케이션 ↔ 캐시, 애플리케이션 ↔ 내부 API)은 AZ 지역성을 고려해 배치합니다. 다만 멀티 AZ는 가용성 요구사항이므로, 전송 요금을 아끼려고 단일 AZ로 모으는 건 프로덕션에서는 잘못된 교환입니다. 줄일 수 있는 건 **같은 AZ에서 끝낼 수 있는데 굳이 넘는 트래픽**뿐입니다.

**무료 티어가 끝나는 날 요금이 생깁니다**
- **증상**: 몇 달간 $0이던 계정에 갑자기 요금이 나옵니다. 리소스는 아무것도 바꾸지 않았습니다.
- **원인**: 2025년 7월부터 신규 계정은 가입 시 **무료 플랜과 유료 플랜을 선택**하고, 무료 플랜은 **6개월 경과 또는 크레딧 소진 중 먼저 오는 시점**에 종료됩니다. ([AWS Free Tier 업데이트](https://aws.amazon.com/about-aws/whats-new/2025/07/aws-free-tier-credits-month-free-plan/)) 종료 시점이 코드 변경과 무관하므로 원인을 엉뚱한 데서 찾게 됩니다. <!-- TODO: 확인 필요 — 크레딧 만료 기간이 Free Tier 약관(12개월)과 FAQ(6개월)에서 다르게 적혀 있어 확정하지 못했습니다. 콘솔의 Credits 페이지로 확인해야 합니다. -->
- **해법**: 계정 생성 시점에 종료일을 캘린더에 적어둡니다. 그 전에 Budgets를 $1 수준으로 하나 걸어두면, 무료 구간이 끝나는 순간이 알림으로 옵니다.

## 10. 요약

견적과 청구서의 차액은 거의 항상 같은 자리에서 나옵니다.

1. **다이어그램에 안 그리는 리소스의 고정비** — NAT Gateway, 퍼블릭 IPv4, 남은 볼륨과 스냅샷
2. **경계를 넘는 내부 트래픽** — AZ 간, IGW 왕복, NAT 경유 S3
3. **트래픽에 비례하는 건수 요금** — 로그 수집, 보관 기간 미설정
4. **소급 불가능한 가시성** — 태그를 미리 붙이지 않으면 지난달은 못 가릅니다

그래서 "비용 최적화"는 나중에 하는 일이 아닙니다. 네트워크 토폴로지를 정할 때, 로그 레벨을 정할 때, 태그를 정할 때 이미 대부분 결정됩니다.

## 11. 참고자료

- [Amazon VPC 요금 — NAT Gateway, VPC 엔드포인트](https://aws.amazon.com/vpc/pricing/)
- [AWS News Blog — 퍼블릭 IPv4 주소 요금과 Public IP Insights](https://aws.amazon.com/blogs/aws/new-aws-public-ipv4-address-charge-public-ip-insights/)
- [Amazon EBS 요금](https://aws.amazon.com/ebs/pricing/)
- [Amazon RDS — DB 인스턴스 일시 중지](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_StopInstance.html)
- [AWS Architecture Blog — 데이터 전송 비용 개요](https://aws.amazon.com/blogs/architecture/overview-of-data-transfer-costs-for-common-architectures/)
- [AWS Networking Blog — ALB/CLB 데이터 전송 비용](https://aws.amazon.com/blogs/networking-and-content-delivery/exploring-data-transfer-costs-for-classic-and-application-load-balancers/)
- [Amazon CloudWatch 요금](https://aws.amazon.com/cloudwatch/pricing/)
- [Amazon S3 요금](https://aws.amazon.com/s3/pricing/)
- [S3 — 완료되지 않은 멀티파트 업로드 정리](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpu-abort-incomplete-mpu-lifecycle-config.html)
- [AWS Billing — 사용자 정의 비용 할당 태그](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/custom-tags.html)
- [AWS Budgets — 비용 관리](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html)
- 관련 문서: `day52-env-separation.md`, `day40-ec2-sizing.md`, `day48-log-level.md`, `day10-route-table.md`, `day54-golden-signals.md`
