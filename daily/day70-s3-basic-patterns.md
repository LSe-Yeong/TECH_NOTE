# 파일을 S3에 저장하기로 했다면 무엇을 먼저 정해야 하는가 — S3 기본 사용 패턴

## 1. 핵심 개념 — S3는 폴더가 아니라 키-값 저장소입니다

S3의 구성 요소는 세 개입니다. **버킷**(이름 공간), **키**(객체 이름), **객체**(바이트 + 메타데이터). 여기에 디렉터리는 없습니다.

`orders/2026/11/a3f1.jpg`는 폴더 세 개 안의 파일이 아니라, **`/`가 포함된 문자열 키 하나**입니다. 콘솔이 트리처럼 그려주는 것은 `/`를 구분자로 보고 화면을 접어주는 것일 뿐입니다.

> 이 한 줄을 넘기면 세 가지가 순서대로 터집니다. 업로드 코드를 복붙했는데 `400 AccessControlListNotSupported`로 실패하고, 고쳐서 올렸더니 100MB 파일 열 개에 톰캣 스레드가 묶여 응답이 멈추고, 그 다음엔 DB에는 첨부 행이 있는데 S3에는 객체가 없습니다. 셋 다 S3 장애가 아닙니다. **저장소를 고른 뒤에 해야 할 네 가지 결정을 안 한 결과**입니다.

이 문서는 "EBS·EFS·S3 중 무엇을 고르는가"에는 답하지 않습니다. 그건 `day64-ebs-efs-s3.md`입니다. 여기서 답하는 질문은 하나입니다 — **S3로 정한 다음, 코드에서 무엇을 먼저 정해야 하는가.**

키-값 구조가 바로 만드는 제약 하나만 미리 적어둡니다. **이름 바꾸기와 폴더 이동이 없습니다.** 키를 바꾸는 유일한 방법은 복사 후 원본 삭제이고, 단일 복사는 5GB까지만 가능하며 그보다 크면 멀티파트 복사를 써야 합니다. 콘솔의 "이름 바꾸기"도 내부적으로는 새 객체를 만들고 원본에 삭제 마커를 붙입니다([CopyObject 문서](https://docs.aws.amazon.com/AmazonS3/latest/userguide/copy-object.html)). 즉 `images/` 아래 10만 개를 `photos/`로 옮기는 작업은 10만 번의 복사와 10만 번의 삭제입니다.

---

## 2. 네 가지 첫 결정

### 2-1. 파일 바이트가 애플리케이션 서버를 통과하는가

둘 중 하나를 고릅니다.

| | 서버 경유 | 프리사인드 URL |
|---|---|---|
| 바이트 경로 | 클라이언트 → 앱 → S3 | 클라이언트 → S3 |
| 앱이 보는 것 | 파일 전체 | 서명 문자열 |
| 검증 시점 | 업로드 후, 서버에서 | 서명할 때 조건으로 미리 |
| 업로드 완료 인지 | 즉시 | 별도 통지 필요 |

**서버 경유의 가격은 스레드입니다.** 업로드가 진행되는 동안 요청 하나가 서블릿 스레드 하나를 계속 점유합니다. 느린 모바일 회선에서 50MB를 올리는 사용자 20명이면 스레드 20개가 수십 초 묶입니다. 같은 바이트가 네트워크를 두 번 타고, 임시 파일이 디스크에 쌓입니다.

Spring Boot는 기본값으로 이 경로를 더 좁혀둡니다. `spring.servlet.multipart.max-file-size`가 `1MB`, `max-request-size`가 `10MB`, `file-size-threshold`가 `0B`입니다(Spring Boot 3.5 `MultipartProperties` 기준). 세 번째 값이 0이라는 건 **모든 업로드가 메모리를 거치지 않고 임시 파일로 떨어진다**는 뜻입니다.

**프리사인드 URL의 가격은 검증 기회입니다.** 서버가 바이트를 안 보므로 "이게 정말 JPEG인가"를 사후에 확인할 수 없습니다. 그래서 서명할 때 키와 `Content-Type`을 박아 넣고, 만료를 짧게 잡습니다. 서명 자체는 로컬 계산이라 S3를 호출하지 않습니다 — 권한이 없어도 URL은 만들어지고, 쓸 때 403이 납니다.

만료 시간에는 함정이 하나 있습니다. SDK와 CLI에서 최대 7일, 콘솔에서는 1분~12시간까지 지정할 수 있지만, **서명에 쓴 자격증명이 먼저 끝나면 거기서 끝납니다.** IAM 역할 자격증명은 역할 세션이 끝날 때 함께 만료되고, EC2 인스턴스 프로파일은 약 6시간, `AssumeRole`은 기본 1시간, ECS 태스크 자격증명은 1~6시간마다 교체됩니다([프리사인드 URL 문서](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html)). 역할로 돌는 서버에서 "7일짜리 공유 링크"는 만들 수 없습니다.

### 2-2. 키를 무엇으로 정하는가

사용자가 올린 파일명을 그대로 키로 쓰는 코드가 가장 흔하고, 가장 빨리 사고가 납니다. 같은 이름이 오면 **조용히 덮어씁니다**(버저닝을 켜지 않았다면 복구 불가). 공백·한글·`%`가 섞여 URL 인코딩 문제가 생기고, 원본 파일명이 그대로 URL에 노출됩니다.

기본 패턴은 이렇습니다.

```
<도메인>/<소유 식별자>/<UUID>.<확장자>     ← 키는 서버가 만듭니다
원본 파일명                                ← DB 컬럼에 저장합니다
```

다운로드 시점에 원래 이름을 돌려주는 건 S3가 해줍니다. `GetObject`에 `response-content-disposition`, `response-content-type` 같은 쿼리 파라미터를 주면 응답 헤더를 그 값으로 덮어씁니다([GetObject API](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html)).

여기서 오래된 통념 하나를 버려야 합니다. **성능 때문에 키 앞에 해시를 붙일 필요는 없습니다.** 현재 문서가 보장하는 수치는 파티션된 프리픽스당 PUT/COPY/POST/DELETE 최소 3,500 TPS, GET/HEAD 최소 5,500 TPS이고, 프리픽스 개수에는 제한이 없습니다. 스케일링은 점진적으로 일어나므로 급증 구간에서 `503 Slow Down`을 볼 수 있습니다([S3 성능 설계 패턴](https://docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance.html)).

그래서 키는 성능이 아니라 **삭제·수명·권한의 단위**로 설계합니다. 라이프사이클 규칙도 프리픽스로 걸리고, IAM 정책의 `Resource`도 프리픽스로 걸립니다. `orders/{orderId}/`로 나눠두면 "이 주문의 첨부 전체"가 한 줄로 표현되고, 파일명을 그대로 쓴 평평한 버킷에서는 그게 불가능합니다.

덮어쓰기를 구조적으로 막고 싶다면 조건부 쓰기를 씁니다. `PutObject`와 `CompleteMultipartUpload`는 "같은 키가 없을 때만 성공"하는 조건을 지원합니다([조건부 요청](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-requests.html)).

### 2-3. 누가 어떻게 읽는가

**새로 만든 버킷은 공개가 아닙니다.** 퍼블릭 액세스 차단 네 가지 설정이 켜져 있고, Object Ownership이 `Bucket owner enforced`라서 **ACL 자체가 비활성**입니다. 이 상태에서 `public-read` 같은 ACL을 담은 `PutObject`는 `400 AccessControlListNotSupported`로 실패합니다([Object Ownership](https://docs.aws.amazon.com/AmazonS3/latest/userguide/about-object-ownership.html)). 2022년 이전 블로그 코드가 그대로 안 도는 이유가 이것입니다.

읽기 경로는 셋 중 하나입니다.

1. **비공개 + 프리사인드 GET** — 권한 검사가 애플리케이션에 남습니다. 사용자별 접근 제어가 필요한 첨부파일의 기본값입니다.
2. **CloudFront + OAC** — 버킷은 계속 비공개로 두고 CDN만 읽게 합니다. 공개 이미지·정적 자산의 기본값입니다.
3. **버킷 정책으로 공개** — 정적 웹사이트 호스팅처럼 범위가 명확할 때만.

프리사인드 GET은 **bearer token입니다.** URL을 가진 사람은 누구나 씁니다. 그래서 만료는 짧게 잡고, HTML에 박아 CDN이나 브라우저에 캐시되게 두지 않습니다. 서버 쪽 상한이 필요하면 버킷 정책에서 `s3:signatureAge` 조건으로 "서명이 10분보다 오래되면 거부"를 걸 수 있습니다.

비용 축도 여기서 갈립니다. 썸네일 50장짜리 목록 화면을 매번 프리사인드 GET으로 받으면 GET 요청이 그대로 쌓입니다. S3 Standard GET은 1,000건당 $0.0004입니다([S3 요금](https://aws.amazon.com/s3/pricing/)). 작은 파일을 대량으로 반복 조회하는 패턴은 2번이 맞습니다.

### 2-4. 언제까지 두는가

라이프사이클 규칙은 세 가지 일을 합니다 — 스토리지 클래스 전환, 만료 삭제, **미완료 멀티파트 업로드 중단**.

세 번째를 거의 모든 버킷에 넣어도 됩니다. 업로드가 중간에 끊기면 이미 올라간 조각이 남고, 이 조각은 객체 목록에 안 보이면서 저장 요금이 붙습니다. `AbortIncompleteMultipartUpload`의 `DaysAfterInitiation`을 7로 두면 S3가 조각을 지웁니다([라이프사이클 예제](https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-configuration-examples.html)).

전환은 더 신중해야 합니다. 저렴한 클래스는 최소 기간과 최소 과금 크기를 같이 가져갑니다.

| 클래스 | 최소 저장 기간 | 최소 과금 크기 | 꺼내기 요금 |
|---|---|---|---|
| S3 Standard | 없음 | 없음 | 없음 |
| S3 Standard-IA / One Zone-IA | 30일 | 128KB | GB당 부과 |
| S3 Glacier Instant Retrieval | 90일 | 128KB | GB당 부과 |
| S3 Intelligent-Tiering | 없음 | 없음 | 없음(객체당 모니터링 요금) |

출처: [스토리지 클래스 비교](https://docs.aws.amazon.com/AmazonS3/latest/userguide/storage-class-intro.html).

읽는 법은 간단합니다. **30일 안에 지워지는 데이터를 Standard-IA로 보내면 더 비쌉니다.** 30일 전에 삭제·덮어쓰기·재전환하면 남은 기간을 비례 계산해 청구합니다. 100KB 파일을 IA에 넣으면 128KB로 과금됩니다. 접근 패턴을 모르겠으면 Intelligent-Tiering이 답이지만, 128KB 미만 객체는 모니터링 대상이 아니라 계속 Frequent Access 티어에 남습니다.

하나 더. 2024년 9월부터 **128KB 미만 객체는 기본적으로 어떤 클래스로도 전환되지 않습니다.** 라이프사이클 규칙을 넣었는데 작은 파일이 그대로 Standard에 있다면 버그가 아니라 이 기본 동작입니다.

---

## 3. 흐름

### 3-1. 코드로 보는 구성

AWS SDK for Java 2.x, Spring Boot 3.x 기준입니다.

```java
@Configuration
public class S3Config {

    @Bean
    public S3Client s3Client() {
        return S3Client.builder().region(Region.AP_NORTHEAST_2).build();
    }

    // S3Presigner는 AutoCloseable이라 빈으로 두면 컨테이너가 close()를 호출합니다
    @Bean
    public S3Presigner s3Presigner() {
        return S3Presigner.builder().region(Region.AP_NORTHEAST_2).build();
    }
}
```

서버 경유 업로드입니다. 키를 서버가 만들고, 원본 파일명은 반환해서 DB가 보관합니다.

```java
@Service
public class OrderAttachmentStorage {

    private static final Set<String> ALLOWED_TYPES = Set.of("image/jpeg", "image/png", "application/pdf");

    private final S3Client s3Client;
    private final String bucket;

    public OrderAttachmentStorage(S3Client s3Client, @Value("${app.s3.bucket}") String bucket) {
        this.s3Client = s3Client;
        this.bucket = bucket;
    }

    public StoredObject store(long orderId, MultipartFile file) throws IOException {
        String contentType = file.getContentType();
        if (!ALLOWED_TYPES.contains(contentType)) {
            throw new UnsupportedAttachmentTypeException(contentType);
        }

        String key = "orders/%d/%s".formatted(orderId, UUID.randomUUID());
        PutObjectRequest request = PutObjectRequest.builder()
                .bucket(bucket)
                .key(key)
                .contentType(contentType)
                .contentLength(file.getSize())
                .build();

        s3Client.putObject(request, RequestBody.fromInputStream(file.getInputStream(), file.getSize()));
        return new StoredObject(key, file.getOriginalFilename(), file.getSize());
    }
}
```

프리사인드 URL 발급입니다. 업로드용은 키와 `Content-Type`을 서명에 넣고, 다운로드용은 원본 파일명을 응답 헤더로 덮어씁니다.

```java
@Service
public class AttachmentUrlIssuer {

    private final S3Presigner presigner;
    private final String bucket;

    // ... 생성자 생략

    public URL issueUploadUrl(long orderId, String contentType) {
        PutObjectRequest target = PutObjectRequest.builder()
                .bucket(bucket)
                .key("orders/%d/%s".formatted(orderId, UUID.randomUUID()))
                .contentType(contentType)   // 클라이언트도 같은 값을 보내야 서명이 맞습니다
                .build();

        PutObjectPresignRequest presignRequest = PutObjectPresignRequest.builder()
                .signatureDuration(Duration.ofMinutes(5))
                .putObjectRequest(target)
                .build();

        return presigner.presignPutObject(presignRequest).url();
    }

    public URL issueDownloadUrl(String objectKey, String originalFilename) {
        String encoded = URLEncoder.encode(originalFilename, StandardCharsets.UTF_8).replace("+", "%20");

        GetObjectRequest target = GetObjectRequest.builder()
                .bucket(bucket)
                .key(objectKey)
                .responseContentDisposition("attachment; filename*=UTF-8''" + encoded)
                .build();

        GetObjectPresignRequest presignRequest = GetObjectPresignRequest.builder()
                .signatureDuration(Duration.ofMinutes(3))
                .getObjectRequest(target)
                .build();

        return presigner.presignGetObject(presignRequest).url();
    }
}
```

### 3-2. 실행 흐름

프리사인드 업로드는 왕복이 두 번입니다.

```
1. 브라우저 → 앱    : POST /orders/42/attachments/upload-url  {contentType: "image/jpeg"}
2. 앱               : 권한 검사 → 키 생성 → 로컬 서명 (S3 호출 없음)
3. 앱 → 브라우저    : {uploadUrl, objectKey}
4. 브라우저 → S3    : PUT uploadUrl  (Content-Type: image/jpeg, 바이트 본문)
5. 브라우저 → 앱    : POST /orders/42/attachments  {objectKey, originalFilename}
6. 앱               : HeadObject로 존재·크기 확인 → DB에 행 저장
```

6번의 `HeadObject`가 중요합니다. 5번 요청은 클라이언트가 보내는 것이므로, 올리지도 않고 보낼 수 있습니다. **서버가 바이트를 안 보는 설계에서는 "진짜 올라갔는지"를 한 번은 물어야 합니다.** 이 확인을 클라이언트 통지에 맡기고 싶지 않다면 S3 이벤트 통지를 쓰는 쪽으로 갑니다.

---

## 4. 두 경로의 사용 시기

**서버 경유를 고릅니다** — 파일이 작고(수 MB), 업로드 직후 서버가 내용을 봐야 하고(이미지 리사이즈, 파싱, 바이러스 검사), 동시 업로드 수가 적을 때. 코드가 한 덩어리로 끝나고 실패 지점이 하나입니다.

**프리사인드를 고릅니다** — 파일이 크거나, 동시 업로더가 많거나, 앱 서버 대역폭·스레드를 쓰고 싶지 않을 때. 대신 "업로드 완료를 어떻게 아는가"와 "검증을 어디서 하는가"라는 설계 숙제가 둘 생깁니다.

작은 파일부터 시작한다면 서버 경유로 시작하는 게 맞습니다. 다만 키 설계(2-2)와 읽기 경로(2-3)는 **처음부터** 정해두어야 합니다. 이 둘은 나중에 바꾸면 이미 저장된 객체 전부를 복사해야 하는 결정이기 때문입니다.

---

## 5. 예제 — DB와 S3, 두 곳에 쓰는 문제

### 5-1. 클린하지 않은 코드 ❌

```java
@Transactional
public void attach(long orderId, MultipartFile file) throws IOException {
    PutObjectRequest request = PutObjectRequest.builder()
            .bucket(bucket)
            .key(file.getOriginalFilename())        // ① 사용자 입력이 그대로 키
            .acl(ObjectCannedACL.PUBLIC_READ)       // ② ACL 비활성 버킷에서 400
            .build();

    s3Client.putObject(request, RequestBody.fromBytes(file.getBytes()));  // ③ 트랜잭션 안에서 수십 초
    attachmentRepository.save(new Attachment(orderId, file.getOriginalFilename()));
}
```

네 가지가 동시에 틀렸습니다.

① 같은 이름을 올리면 다른 사람의 파일을 덮어씁니다. ② 기본 설정 버킷에서는 `AccessControlListNotSupported`로 실패합니다. ③ 업로드가 끝날 때까지 DB 커넥션을 쥐고 있습니다 — 업로드 시간이 곧 커넥션 점유 시간입니다. ④ `save()` 이후 커밋이 실패하면 DB는 되감기지만 **S3 객체는 그대로 남습니다.**

③의 원리는 `day20-service-layer-design.md`와 같습니다. 트랜잭션 경계 안에 외부 I/O를 넣으면 풀이 마릅니다.

### 5-2. 개선한 코드 ✔️

핵심은 **두 저장소에 원자적으로 쓸 방법이 없다는 걸 인정하고, 실패 방향을 고정하는 것**입니다. 남길 쪽은 "고아 객체"입니다. DB에 없는 S3 객체는 라이프사이클이나 정리 배치로 수거할 수 있지만, S3에 없는 DB 행은 사용자에게 깨진 링크로 보입니다.

```java
@Service
public class OrderAttachmentService {

    // 트랜잭션 밖: 업로드가 끝난 뒤에야 짧은 트랜잭션을 엽니다
    public void attach(long orderId, MultipartFile file) throws IOException {
        StoredObject stored = storage.store(orderId, file);
        register(orderId, stored);
    }

    @Transactional
    public void register(long orderId, StoredObject stored) {
        orderRepository.findById(orderId).orElseThrow(OrderNotFoundException::new);
        attachmentRepository.save(Attachment.of(orderId, stored));
    }
}
```

삭제는 순서를 뒤집습니다. **커밋이 성공한 뒤에 지웁니다.**

```java
@Transactional
public void detach(long attachmentId) {
    Attachment attachment = attachmentRepository.findById(attachmentId)
            .orElseThrow(AttachmentNotFoundException::new);
    attachmentRepository.delete(attachment);
    eventPublisher.publishEvent(new AttachmentDetached(attachment.getObjectKey()));
}

@TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
public void deleteObject(AttachmentDetached event) {
    s3Client.deleteObject(b -> b.bucket(bucket).key(event.objectKey()));
}
```

먼저 지우고 커밋에 실패하면 **복구 불가능한 데이터 유실**입니다. 반대로 커밋 후 삭제에 실패하면 고아 객체가 남습니다. 둘 다 불완전하지만 손해의 크기가 다릅니다. 이중 쓰기 일반론은 `day69-message-queue-why.md`에서 다룹니다.

---

## 6. 함정

**① `AccessControlListNotSupported` 400**
- **증상**: 예제 코드를 그대로 썼는데 업로드가 400으로 실패합니다.
- **원인**: 새 버킷은 Object Ownership이 `Bucket owner enforced`라 ACL이 비활성입니다. `public-read`를 담은 `PutObject`는 거부됩니다.
- **해법**: ACL을 지웁니다. 공개가 필요하면 CloudFront + OAC나 버킷 정책으로 해결합니다. ACL을 되살리는 건 거의 항상 잘못된 방향입니다.

**② 프리사인드 URL이 지정한 시간보다 빨리 죽습니다**
- **증상**: 7일로 발급했는데 몇 시간 뒤 `ExpiredToken`이 납니다.
- **원인**: 서명에 쓴 역할 자격증명이 먼저 만료됩니다. URL 수명은 둘 중 짧은 쪽입니다.
- **해법**: 짧은 수명(분 단위)으로 발급하고 필요할 때 다시 발급합니다. 장기 공유가 요구사항이면 프리사인드가 아니라 CloudFront 서명 URL 쪽을 봅니다.

**③ `SignatureDoesNotMatch`**
- **증상**: 서버는 URL을 잘 만들었는데 클라이언트 PUT이 403입니다.
- **원인**: 서명에 포함한 헤더와 실제 요청 헤더가 다릅니다. `Content-Type`을 서명해두고 클라이언트가 안 보내거나 다른 값을 보내는 경우가 가장 많습니다. 기업 프록시의 헤더 변조, 서버 시계 틀어짐도 원인입니다.
- **해법**: 서명 대상 헤더를 최소로 줄이고, 클라이언트가 보내야 하는 헤더를 응답에 함께 내려줍니다. 서버 시계는 NTP로 맞춥니다.

**④ 업로드가 1MB에서 멈춥니다**
- **증상**: 로컬 테스트는 통과했는데 실제 파일에서 `MaxUploadSizeExceededException`이나 413이 납니다.
- **원인**: Spring Boot 기본 상한(`max-file-size=1MB`, `max-request-size=10MB`), 그리고 앞단 ALB·nginx의 본문 크기 제한입니다. 둘은 별개입니다.
- **해법**: 양쪽을 다 올립니다. 그리고 "올려야 하는 값이 크다"면 그 자체가 2-1의 결정을 다시 보라는 신호입니다.

**⑤ 목록에 없는 객체의 저장 요금**
- **증상**: 객체 수와 용량이 안 맞고, 버킷을 비웠는데도 요금이 남습니다.
- **원인**: 미완료 멀티파트 업로드 조각입니다. `ListObjects`에 안 나오지만 저장 요금은 붙습니다.
- **해법**: `AbortIncompleteMultipartUpload` 라이프사이클 규칙을 넣습니다. 이미 쌓였다면 `ListMultipartUploads`로 확인하고 중단합니다.

**⑥ IA로 옮겼는데 비용이 늘었습니다**
- **증상**: 라이프사이클로 Standard-IA 전환을 켠 뒤 청구액이 올라갑니다.
- **원인**: 30일 최소 저장 기간, 128KB 최소 과금 크기, GB당 꺼내기 요금 세 가지입니다. 수명이 짧거나 작은 파일이 많거나 조회가 잦으면 전부 손해 쪽으로 작동합니다.
- **해법**: 전환 기준을 "생성 후 N일"이 아니라 "실제 접근 패턴"으로 다시 셉니다. 패턴을 모르면 Intelligent-Tiering을 씁니다.

---

## 7. 참고자료

- [S3 프리사인드 URL](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html)
- [Object Ownership과 ACL 비활성](https://docs.aws.amazon.com/AmazonS3/latest/userguide/about-object-ownership.html)
- [퍼블릭 액세스 차단](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html)
- [S3 성능 설계 패턴](https://docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance.html)
- [스토리지 클래스 비교](https://docs.aws.amazon.com/AmazonS3/latest/userguide/storage-class-intro.html)
- [라이프사이클 설정 예제](https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-configuration-examples.html)
- [객체 복사·이동·이름 바꾸기](https://docs.aws.amazon.com/AmazonS3/latest/userguide/copy-object.html)
- [S3 요금](https://aws.amazon.com/s3/pricing/)
- 관련 챕터: `day64-ebs-efs-s3.md`, `day20-service-layer-design.md`, `day69-message-queue-why.md`

<!-- TODO: 확인 필요 — S3 Standard의 PUT/COPY/POST/LIST 요청 단가(us-east-1 기준 1,000건당 $0.005로 널리 인용됨)는 공식 요금 페이지의 표가 검증 시점에 렌더링되지 않아 본문에서 제외했습니다. 리전별로 다르므로 쓸 때는 요금 페이지에서 직접 확인해야 합니다. -->
<!-- TODO: 확인 필요 — 3-1의 S3Presigner/PutObjectPresignRequest API 이름은 AWS SDK for Java 2.x 기준으로 작성했으나, 공식 SDK 가이드 페이지 본문을 직접 열어 교차검증하지 못했습니다. 컴파일로 확인이 필요합니다. -->
