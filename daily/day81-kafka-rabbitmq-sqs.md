# Kafka · RabbitMQ · SQS — 셋은 무엇을 기준으로 고르는가

## 1. 핵심 개념

셋은 모두 "메시지 큐"로 묶여 불리지만, 같은 물건이 아닙니다. 하나는 **읽어도 지워지지 않는 로그**이고, 하나는 **라우팅 규칙을 가진 브로커**이고, 하나는 **운영할 게 없는 관리형 큐**입니다.

> 이 차이를 모르고 고르면, 문제는 성능이 아니라 **뒤늦게 발견되는 불가능**으로 나타납니다. SQS로 다 만들어놓고 "이 이벤트 정산 팀도 받게 해주세요"라는 요청이 오면, 큐에 컨슈머를 하나 더 붙여서는 해결되지 않습니다. 메시지가 복제되는 게 아니라 **나눠 먹힙니다.** 반대로 작업 분배만 필요한데 Kafka를 깔면, 파티션 수라는 천장이 생기고 운영할 클러스터가 하나 늘어납니다.

이 문서는 하나의 질문에 답합니다. **이 세 제품을 무엇을 기준으로 고르는가.** 처리량 벤치마크가 아니라, 제품을 바꿔야만 풀리는 축을 찾는 것이 목표입니다.

기준 버전은 Apache Kafka 4.3(2026년 5월 22일 릴리스), RabbitMQ 4.4, Amazon SQS(2026년 11월 현재 문서)입니다.

## 2. 기준 1 — 읽은 메시지가 사라지는가

가장 큰 축이고, 나머지 차이의 절반이 여기서 파생됩니다.

**Kafka는 읽어도 지우지 않습니다.** 공식 문서는 "전통적인 메시징 시스템과 달리 이벤트는 소비된 후에 삭제되지 않는다"고 적고, 언제 버릴지는 토픽별 보관 설정으로 정합니다([Kafka Introduction](https://kafka.apache.org/intro)). 컨슈머가 어디까지 읽었는지는 컨슈머 쪽 오프셋이고, 메시지의 상태가 아닙니다.

그래서 Kafka에서는 다음이 전부 공짜입니다.

- 소비자 그룹을 하나 더 만들면 같은 데이터를 처음부터 다시 읽습니다
- 버그를 고친 뒤 과거 데이터를 재처리합니다
- 신규 서비스가 나중에 합류해서 이력부터 읽습니다

**RabbitMQ와 SQS는 지웁니다.** 컨슈머가 ack(SQS는 `DeleteMessage`)하면 메시지는 큐에서 없어집니다. 같은 메시지를 둘이 받으려면 **메시지를 받을 통을 두 개 만들어야** 합니다. RabbitMQ는 exchange에 큐 두 개를 바인딩하고, SQS는 SNS 토픽을 앞에 세워 큐 두 개를 구독시킵니다([Fanout SNS notifications to SQS queues](https://docs.aws.amazon.com/sns/latest/dg/sns-sqs-as-subscriber.html)).

여기서 중요한 건 "SQS는 팬아웃이 안 된다"가 아니라 **팬아웃 구조를 나중에 끼워 넣기 어렵다**는 점입니다. 프로듀서가 이미 큐 URL로 직접 보내고 있으면, SNS를 중간에 넣는 순간 프로듀서 코드와 권한 정책을 다 고쳐야 합니다. Kafka에서는 구독자를 추가하는 쪽만 손대면 됩니다.

## 3. 기준 2 — 병렬성의 단위는 무엇인가

컨슈머를 늘렸는데 처리량이 안 늘어나는 이유가 여기 있습니다.

**Kafka 컨슈머 그룹: 파티션 수가 천장입니다.** 한 파티션은 그룹 안에서 정확히 한 컨슈머에게만 배정됩니다. 파티션 4개짜리 토픽에 컨슈머 2개면 각자 2개를 읽고, 컨슈머를 10개로 늘리면 **6개는 아무것도 안 하고 놉니다.** 공식 javadoc은 스레드당 컨슈머 하나 모델에서 "전체 스레드 수가 전체 파티션 수로 제한된다"고 명시합니다([KafkaConsumer javadoc](https://kafka.apache.org/43/javadoc/org/apache/kafka/clients/consumer/KafkaConsumer.html)).

**RabbitMQ: 큐 하나에 컨슈머를 원하는 만큼 붙입니다.** 천장은 큐의 개수가 아니라 컨슈머의 처리 속도입니다. 분배 단위는 메시지 하나이고, 미리 몇 개까지 쥐게 할지는 prefetch(`basic.qos`)로 정합니다.

**SQS 표준 큐: 사실상 제한이 없습니다.** 공식 문서는 표준 큐가 액션별로 "매우 높고 거의 무제한에 가까운" API 호출을 지원한다고 적습니다([SQS queue types](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-queue-types.html)). 컨슈머를 100개로 늘려도 설정할 게 없습니다.

| | 병렬 처리 단위 | 늘리는 방법 |
|---|---|---|
| Kafka 컨슈머 그룹 | 파티션 | 파티션 수를 늘립니다(되돌릴 수 없음) |
| RabbitMQ | 메시지 | 컨슈머를 붙입니다 |
| SQS 표준 | 메시지 | 컨슈머를 붙입니다 |
| SQS FIFO | 메시지 그룹 | `MessageGroupId`를 분산시킵니다 |

작업 분배(worker pool)가 목적이라면 Kafka는 가장 불편한 선택입니다. 파티션 수를 처리량 상한으로 미리 결정해야 하고, 작업 하나가 10분 걸리면 그 파티션의 뒤쪽 작업 전부가 10분 기다립니다. **한 메시지의 지연이 같은 파티션의 모든 메시지로 전파됩니다.**

## 4. 기준 3 — 라우팅을 누가 하는가

**RabbitMQ만 브로커가 라우팅 로직을 가집니다.** 프로듀서는 exchange에 라우팅 키를 붙여 보내고, "어느 큐로 갈지"는 exchange 타입과 바인딩이 정합니다. `order.created`는 알림 큐와 정산 큐로, `order.cancelled.vip`는 별도 큐로 — 이 분기가 **애플리케이션 코드가 아니라 브로커 설정**에 있습니다. 운영 중에 바인딩만 추가해서 새 소비자를 끼울 수 있습니다.

**Kafka는 토픽만 있습니다.** 필터링은 컨슈머 책임입니다. "VIP 주문만 받는다"를 하려면 토픽을 따로 만들거나, 전부 읽고 조건에 안 맞는 걸 버립니다. Kafka Streams로 걸러 다른 토픽에 다시 쓰는 방법도 같은 비용입니다.

**SQS는 라우팅이 없습니다.** 큐는 그냥 큐입니다. 조건 분기가 필요하면 앞에 SNS(메시지 필터링 정책)나 EventBridge(규칙)를 세웁니다. 즉 SQS를 고르는 것은 보통 **SQS 단독이 아니라 SNS/EventBridge + SQS 조합**을 고르는 일입니다.

이 축은 "복잡한 라우팅이 필요하면 RabbitMQ"라는 결론으로 끝나지 않습니다. 반대쪽 대가가 있습니다. 라우팅이 브로커 설정에 있으면 **메시지가 어디로 가는지 코드를 읽어서는 알 수 없습니다.** 저장소에 없는 설정이 운영 동작을 결정합니다. 그래서 RabbitMQ를 쓸 때는 exchange/바인딩 선언을 애플리케이션 코드(`@Bean Binding`)나 IaC로 관리해서 저장소 안으로 되돌리는 쪽이 안전합니다.

## 5. 기준 4 — 순서와 중복을 어디까지 보장하는가

"순서 보장"은 제품 단위가 아니라 **범위 단위**로 봐야 합니다.

**Kafka — 파티션 안에서만.** 같은 키는 같은 파티션에 들어가고, 한 파티션의 이벤트는 쓰인 순서대로 읽힙니다([Kafka Introduction](https://kafka.apache.org/intro)). 즉 `userId`를 키로 쓰면 그 사용자의 이벤트는 순서가 보장되고, 사용자 간 순서는 보장되지 않습니다. 대개 이게 실무에서 필요한 전부입니다.

**RabbitMQ — 큐에 넣은 순서로 나가지만, 컨슈머가 둘 이상이면 처리 순서는 깨집니다.** 2번 컨슈머가 먼저 끝날 수 있고, 실패한 메시지가 requeue되면 뒤로 갑니다. 순서가 필요하면 큐별 컨슈머를 1개로 두는 것이고, 그건 곧 병렬성을 포기하는 것입니다.

**SQS 표준 — best-effort입니다.** 공식 문서가 "순서대로 도착하지 않을 수 있다"고 명시합니다. 순서가 필요하면 FIFO 큐를 쓰고, 보장 범위는 `MessageGroupId` 안입니다.

그리고 FIFO의 가격표가 여기서 중요합니다. 고throughput 모드를 켜지 않은 FIFO 큐는 **파티션당 API 액션별 300 TPS**이고, 10개씩 배치로 묶으면 초당 3,000건입니다. 고throughput 모드를 켜면 리전마다 상한이 다릅니다 — 버지니아 북부·오레곤·아일랜드는 배치 없이 최대 70,000 TPS, 그 외 대부분 리전의 기본값은 2,400 TPS입니다([SQS message quotas](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/quotas-messages.html)).

> 순서를 공짜로 주는 제품은 없습니다. Kafka는 파티션 수로, RabbitMQ는 컨슈머 수로, SQS FIFO는 TPS로 값을 받습니다.

### 5-1. 중복 방어 장치도 범위가 다릅니다

세 제품 모두 기본은 at-least-once입니다. 그 위에 올려주는 장치가 다릅니다.

- **SQS FIFO**: `MessageDeduplicationId`가 같은 메시지를 **5분**의 중복 제거 구간 안에서 걸러냅니다. 본문 해시로 자동 생성하게(content-based deduplication) 할 수도 있습니다([Exactly-once processing in Amazon SQS](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/FIFO-queues-exactly-once-processing.html)). 5분이 지난 재전송은 통과합니다.
- **Kafka**: 멱등 프로듀서가 재시도로 생기는 **프로듀서 쪽** 중복 기록을 막고, 트랜잭션으로 "읽고 처리하고 쓰기"를 원자적으로 묶습니다. 둘 다 Kafka 안에서 끝나는 범위이고, 컨슈머가 DB나 외부 API를 건드리는 순간 보장은 끝납니다.
- **RabbitMQ**: 중복 제거 기능이 없습니다. publisher confirms로 "브로커가 받았다"까지 확인하고, 그다음은 애플리케이션 책임입니다.

공통 결론은 하나입니다. **어느 제품을 고르든 컨슈머는 멱등해야 합니다.** 제품의 중복 제거 기능은 재시도 구간을 좁혀줄 뿐, "정확히 한 번"을 만들어주지 않습니다.

## 6. 기준 5 — 누가 운영하는가

이 축이 작아 보이지만, 팀이 작으면 결정적입니다.

**SQS는 운영할 것이 없습니다.** 클러스터도, 디스크도, 버전 업그레이드도 없습니다. 대신 세부 제어도 없습니다. 보관 기간은 기본 4일(최소 60초 ~ 최대 14일), 메시지 최대 크기는 1 MiB, visibility timeout 기본 30초(최대 12시간) — 전부 정해진 범위 안에서만 조정합니다([SQS message quotas](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/quotas-messages.html)). 최대 크기는 2025년 8월에 256 KiB에서 1 MiB로 올라갔습니다([AWS What's New](https://aws.amazon.com/about-aws/whats-new/2025/08/amazon-sqs-max-payload-size-1mib)).

**Kafka와 RabbitMQ는 상태를 가진 클러스터입니다.** 직접 운영하면 디스크, 복제, 리밸런스, 버전 업그레이드가 다 내 일이 됩니다. 두 제품 모두 최근 메이저 버전에서 운영 모델이 바뀌었습니다.

- Kafka 4.0부터 ZooKeeper가 **제거**되어 KRaft 모드만 남았습니다. 3.x에서 올라오려면 3.9에서 KRaft로 먼저 마이그레이션해야 합니다([Kafka 4.0 announcement](https://kafka.apache.org/blog/2025/03/18/apache-kafka-4.0.0-release-announcement/)).
- RabbitMQ 4.0.1에서 classic queue의 미러링이 **제거**되었습니다. 복제가 필요하면 quorum queue나 stream을 씁니다([RabbitMQ 4.0.1 release notes](https://github.com/rabbitmq/rabbitmq-server/releases/tag/v4.0.1)).

Quorum queue는 Raft 기반이고, 전달 모드와 무관하게 **항상 디스크에 씁니다.** 메시지당 최소 32바이트의 인메모리 인덱스를 유지하므로 메시지 3만 개당 약 1 MB입니다. 공식 문서는 큐가 5,000개를 넘는 토폴로지는 재검토하라고 하고, 500만 건 이상의 백로그나 큰 팬아웃은 stream이 더 맞다고 안내합니다([Quorum Queues](https://www.rabbitmq.com/docs/quorum-queues)). **RabbitMQ는 큐가 짧게 유지된다는 가정 위에 설계된 제품입니다.**

## 7. 경계가 흐려지는 중 — Share Group과 Stream

2번에서 세운 축이 요즘 양쪽에서 침식되고 있습니다. 이걸 알고 있으면 "Kafka는 큐가 아니다" 같은 오래된 설명을 피할 수 있습니다.

**Kafka에 큐 모드가 생겼습니다.** KIP-932의 share group이 Kafka 4.0에서 미리보기로 들어왔고, **4.2.0(2026년 2월 17일)에서 프로덕션 준비 완료로 선언**되었습니다([Kafka 4.2.0 announcement](https://kafka.apache.org/blog/2026/02/17/apache-kafka-4.2.0-release-announcement/)). share group에서는 여러 컨슈머가 **같은 파티션을 동시에** 읽고, 레코드 단위로 확인합니다. 전달된 레코드는 기본 30초(`group.share.record.lock.duration.ms`) 동안 한 컨슈머에게 잠기고, 확인 없이 만료되면 다른 컨슈머가 가져갈 수 있습니다. 확인 타입은 ACCEPT / RELEASE / REJECT / RENEW입니다([KafkaShareConsumer javadoc](https://kafka.apache.org/43/javadoc/org/apache/kafka/clients/consumer/KafkaShareConsumer.html)).

SQS의 visibility timeout과 같은 모델입니다. 그리고 대가도 명시돼 있습니다 — javadoc은 이 유연한 분배를 "레코드 순서를 대가로" 얻는다고 적습니다. **파티션 수 천장을 없애는 대신 순서를 버립니다.**

**RabbitMQ에 로그가 생겼습니다.** Stream은 append-only 로그이고, 읽어도 지워지지 않습니다. 컨슈머는 `x-stream-offset`으로 시작 지점을 `first` / `last` / `next` / 특정 오프셋 / 타임스탬프 / `7D` 같은 상대 구간 중에서 고릅니다. 보관은 `max-age`와 `max-length-bytes`로 정합니다. 대신 TTL, DLX, 메시지 우선순위, poison message 처리를 **지원하지 않습니다**([Streams](https://www.rabbitmq.com/docs/streams)).

정리하면 이렇습니다.

- Kafka 컨슈머 그룹 ↔ RabbitMQ stream — 로그 모델, 재생 가능
- Kafka share group ↔ RabbitMQ quorum queue ↔ SQS — 큐 모델, 레코드 단위 확인

<!-- TODO: 확인 필요 — share group의 운영 사례(리밸런스 비용, 모니터링 지표 성숙도)는 아직 공개 자료가 적습니다. 4.2에서 프로덕션 준비 완료로 선언된 것은 확인했지만, 기존 컨슈머 그룹을 share group으로 교체하는 것을 권하기에는 근거가 부족합니다. -->

## 8. 코드로 보는 차이

같은 "주문 완료" 처리를 세 제품으로 받습니다. 차이는 문법이 아니라 **실패했을 때 무엇이 일어나는지**에 있습니다.

```java
// Kafka — spring-kafka. 오프셋 커밋이 곧 "처리했다"는 기록
@KafkaListener(topics = "order.completed", groupId = "settlement")
public void onOrderCompleted(OrderCompletedEvent event) {
    settlementService.record(event.orderId());
    // 예외가 나가면 오프셋을 커밋하지 않습니다.
    // 같은 파티션의 다음 메시지도 그대로 멈춥니다(head-of-line blocking).
}
```

```java
// RabbitMQ — spring-boot-starter-amqp. 메시지 하나 단위로 실패를 처리
@RabbitListener(queues = "settlement.order.completed")
public void onOrderCompleted(OrderCompletedEvent event) {
    settlementService.record(event.orderId());
    // 예외가 나가면 이 메시지만 재전달되고, 다른 메시지는 계속 처리됩니다.
    // quorum queue는 재전달 한도 기본값이 20이고, 넘으면 DLX로 보내거나 버립니다.
}
```

```java
// SQS — spring-cloud-aws-starter-sqs 3.x. 삭제하지 않으면 다시 보입니다
@SqsListener("settlement-order-completed")
public void onOrderCompleted(OrderCompletedEvent event) {
    settlementService.record(event.orderId());
    // 정상 반환 시 DeleteMessage 가 호출됩니다.
    // 예외가 나가면 visibility timeout 이 지난 뒤 다시 수신됩니다.
}
```

세 코드가 비슷해 보이지만, 처리 시간이 1분인데 설정이 기본값이면 결과가 다릅니다. Kafka는 뒤쪽 메시지가 1분씩 밀립니다. RabbitMQ는 다른 컨슈머가 다른 메시지를 계속 처리합니다. SQS는 visibility timeout 30초가 먼저 지나서 **아직 처리 중인 메시지를 다른 컨슈머가 또 받습니다.**

## 9. 선택 순서

### 9-1. 다섯 축 요약

| 축 | Kafka | RabbitMQ | SQS |
|---|---|---|---|
| 읽은 메시지 | 남습니다(보관 기간까지) | ack하면 사라집니다(stream은 남음) | 삭제하면 사라집니다 |
| 병렬성 단위 | 파티션 | 메시지 | 메시지(FIFO는 메시지 그룹) |
| 라우팅 주체 | 없음(컨슈머가 필터) | 브로커(exchange·바인딩) | 없음(SNS·EventBridge 필요) |
| 순서 범위 | 파티션 안 | 단일 컨슈머일 때만 | 표준은 best-effort, FIFO는 그룹 안 |
| 운영 부담 | 클러스터(KRaft) | 클러스터(Raft 쿼럼) | 없음 |
| 긴 백로그 | 설계에 포함됨 | 피해야 함 | 최대 14일 |

### 9-2. 걸러내는 순서

기능 표를 비교하는 대신 이 순서로 걸러냅니다. 위쪽 질문이 아래쪽보다 되돌리기 어렵습니다.

1. **같은 메시지를 지금 또는 나중에 여러 소비자가 각자 읽어야 하는가, 과거를 재처리해야 하는가** → 예라면 Kafka(또는 RabbitMQ stream). 이건 나중에 큐에서 옮겨 붙이기 가장 어려운 요구입니다.
2. **아니라면, 운영 인력을 쓸 수 있는가** → 아니라면 SQS. AWS 안에 있고 작업 분배가 목적이라면 대개 여기서 끝납니다.
3. **브로커가 조건 분기를 해줘야 하는가** → 예라면 RabbitMQ. 아니라면 SQS + SNS 필터링으로 충분한지 먼저 확인합니다.
4. **처리량이 파티션 수로 제한돼도 괜찮은가** → 아니라면 작업 큐에 Kafka 컨슈머 그룹을 쓰지 않습니다.
5. **순서가 어느 범위에서 필요한가** → 전역 순서가 필요하다고 느껴지면, 대개는 요구사항을 다시 보는 게 맞습니다. 멱등하게 만들면 순서 요구가 사라지는 경우가 많습니다(`daily/day21-idempotency.md`).

이 순서대로면 "셋 중 뭐가 빠른가"는 거의 마지막 질문이고, 실무에서 그 답이 결정을 바꾸는 일은 드뭅니다.

## 10. 함정

**컨슈머를 하나 더 붙였는데 메시지가 반씩만 옵니다**
- **증상**: SQS(또는 RabbitMQ) 큐에 알림 서비스와 정산 서비스를 함께 붙였는데, 각자 메시지의 절반만 받습니다.
- **원인**: 큐는 경쟁 소비자(competing consumers) 모델입니다. 메시지 하나는 한 컨슈머에게만 갑니다. 같은 `group.id`를 쓴 Kafka 컨슈머 그룹도 똑같습니다.
- **해법**: 소비자별로 통을 나눕니다. SQS는 SNS 토픽을 앞에 세우고 큐를 두 개 구독시킵니다. RabbitMQ는 exchange에 큐를 둘 바인딩합니다. Kafka는 `group.id`를 다르게 주면 됩니다.

**Kafka 파티션을 늘린 뒤 같은 사용자 이벤트의 순서가 깨졌습니다**
- **증상**: 처리량을 늘리려고 파티션을 3개에서 6개로 늘렸는데, 이후 특정 사용자의 이벤트가 역순으로 처리됩니다.
- **원인**: 기본 파티셔너는 키 해시를 파티션 수로 나눈 나머지를 씁니다. 파티션 수가 바뀌면 같은 키가 다른 파티션으로 갑니다. 기존 파티션에 남은 이벤트와 새 파티션에 들어가는 이벤트의 순서 관계가 사라집니다.
- **해법**: 파티션 수는 초기에 여유 있게 잡습니다(줄일 수는 없습니다). 이미 늘려야 한다면 새 토픽을 만들어 컨슈머를 전환하거나, 전환 시점에 해당 키의 처리를 멈춥니다.

**SQS FIFO로 바꾸니 초당 300건에서 안 올라갑니다**
- **증상**: 처리량이 특정 값에서 평평해지고, 컨슈머를 늘려도 그대로입니다.
- **원인**: `MessageGroupId`를 상수나 `"default"`로 넣었습니다. 모든 메시지가 한 그룹이면 한 파티션에 몰리고, 고throughput 모드가 아닌 FIFO 큐는 파티션당 API 액션별 300 TPS입니다([SQS message quotas](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/quotas-messages.html)).
- **해법**: 순서가 실제로 필요한 범위를 그룹 ID로 씁니다(보통 `orderId`나 `userId`). 그룹이 많아야 병렬 처리가 됩니다. 그래도 부족하면 고throughput 모드를 켜고, 리전별 기본 상한이 다르다는 걸 염두에 둡니다.

**같은 메시지가 중복 처리되는데 재시도 로그는 없습니다**
- **증상**: SQS 컨슈머가 예외 없이 끝났는데 같은 주문이 두 번 정산됩니다.
- **원인**: 처리 시간이 visibility timeout(기본 30초)보다 길어 삭제 전에 메시지가 다시 보이게 됐습니다. 두 번째 수신은 "재시도"가 아니라 정상 동작입니다.
- **해법**: visibility timeout을 최악의 처리 시간보다 길게 잡거나, 처리 중 주기적으로 연장합니다. 근본 해법은 처리를 멱등하게 만드는 것입니다. Kafka share group도 같은 모델이라 같은 함정이 있습니다.

**RabbitMQ 4.x로 올렸는데 노드 하나 죽으니 메시지가 사라졌습니다**
- **증상**: 3.x에서는 버티던 구성이 4.x에서 노드 장애 시 메시지를 잃습니다.
- **원인**: 4.0.1에서 classic queue 미러링이 제거되었습니다. 미러링을 기대하고 쓰던 classic queue는 이제 복제되지 않는 큐입니다([RabbitMQ 4.0.1 release notes](https://github.com/rabbitmq/rabbitmq-server/releases/tag/v4.0.1)).
- **해법**: 복제가 필요한 큐를 quorum queue로 전환합니다. 업그레이드 전에 큐 타입을 목록으로 확인하는 게 먼저입니다. <!-- TODO: 확인 필요 — 기존 ha-mode 정책이 4.x에서 조용히 무시되는지(에러 없이 무동작인지) 공식 문서에서 확정하지 못했습니다. -->

**큐에 쌓이기 시작하자 RabbitMQ 노드 전체가 느려졌습니다**
- **증상**: 한 큐의 백로그가 수백만 건으로 늘어난 뒤 무관한 다른 큐의 처리도 느려집니다.
- **원인**: quorum queue는 메시지당 최소 32바이트의 인메모리 인덱스를 유지하고, 노드의 쓰기 전 로그를 공유합니다. 공식 문서는 500만 건 이상의 긴 백로그는 stream이 더 맞다고 안내합니다([Quorum Queues](https://www.rabbitmq.com/docs/quorum-queues)).
- **해법**: RabbitMQ를 쓸 때는 큐 깊이에 알림을 걸고 짧게 유지합니다. 백로그 자체가 설계의 일부라면(재처리, 장기 버퍼) 제품 선택이 틀린 것입니다.

## 11. 참고자료

- [Apache Kafka Introduction](https://kafka.apache.org/intro)
- [Apache Kafka 4.0.0 Release Announcement](https://kafka.apache.org/blog/2025/03/18/apache-kafka-4.0.0-release-announcement/)
- [Apache Kafka 4.2.0 Release Announcement](https://kafka.apache.org/blog/2026/02/17/apache-kafka-4.2.0-release-announcement/)
- [Apache Kafka 4.3.0 Release Announcement](https://kafka.apache.org/blog/2026/05/22/apache-kafka-4.3.0-release-announcement/)
- [KafkaConsumer javadoc](https://kafka.apache.org/43/javadoc/org/apache/kafka/clients/consumer/KafkaConsumer.html) / [KafkaShareConsumer javadoc](https://kafka.apache.org/43/javadoc/org/apache/kafka/clients/consumer/KafkaShareConsumer.html)
- [RabbitMQ Quorum Queues](https://www.rabbitmq.com/docs/quorum-queues) / [Streams](https://www.rabbitmq.com/docs/streams) / [Release Information](https://www.rabbitmq.com/release-information)
- [RabbitMQ 4.0.1 release notes](https://github.com/rabbitmq/rabbitmq-server/releases/tag/v4.0.1)
- [Amazon SQS queue types](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-queue-types.html) / [message quotas](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/quotas-messages.html) / [exactly-once processing](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/FIFO-queues-exactly-once-processing.html)
- [Fanout SNS notifications to SQS queues](https://docs.aws.amazon.com/sns/latest/dg/sns-sqs-as-subscriber.html)
- [Amazon SQS increases maximum message payload size to 1 MiB](https://aws.amazon.com/about-aws/whats-new/2025/08/amazon-sqs-max-payload-size-1mib)
- 관련 문서: `daily/day69-message-queue-why.md`, `daily/day21-idempotency.md`, `daily/day75-event-driven-basics.md`
