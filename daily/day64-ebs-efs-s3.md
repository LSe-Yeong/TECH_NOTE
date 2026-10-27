# 저장소는 무엇으로 나누는가 — EBS·EFS·S3는 무엇을 기준으로 고르는가

## 1. 핵심 개념 — 셋은 같은 종류의 물건이 아닙니다

세 서비스를 "AWS 저장소 3종"으로 묶어 외우면 선택이 안 됩니다. 셋은 **애플리케이션에 노출되는 인터페이스**가 다릅니다.

| | 노출되는 것 | 코드에서 접근하는 방법 |
|---|---|---|
| EBS | 블록 디바이스(`/dev/nvme1n1`) | OS가 파일시스템을 올리고, 코드는 로컬 경로를 씁니다 |
| EFS | NFS 파일시스템 | 마운트 포인트를 로컬 경로처럼 씁니다 |
| S3 | HTTP API | SDK로 `PutObject` / `GetObject`를 호출합니다 |

> 이 구분을 모르고 시작하면 거의 항상 같은 사고가 납니다. 업로드 파일을 EC2 로컬 경로에 저장하는 겁니다. 로컬에서는 완벽하게 돌아갑니다. 그리고 인스턴스를 2대로 늘리는 순간 파일이 절반만 보이고, 배포로 인스턴스가 교체되는 순간 전부 사라집니다. 코드에 버그는 없습니다. **저장소를 잘못 고른 것**입니다.

이 문서는 "셋 중 무엇을 고르는가"에만 답합니다.

---

## 2. 선택을 결정하는 네 가지 축

기능 목록을 비교하면 끝이 안 납니다. 실제로 결정을 바꾸는 축은 네 개입니다.

### 2-1. 공유 범위 — 몇 대가 동시에 쓰는가

가장 먼저 걸리는 축이고, 대부분 여기서 답이 나옵니다.

**EBS는 기본적으로 인스턴스 1대 전용입니다.** 예외가 Multi-Attach인데, 조건이 빡빡합니다. `io1`/`io2` 볼륨만 지원하고, **같은 AZ 안의** Nitro 기반 인스턴스 최대 16대까지만 붙습니다. 부팅 볼륨으로는 못 씁니다. 결정적으로 AWS 문서가 이렇게 못 박습니다 — XFS나 EXT4 같은 일반 파일시스템은 여러 서버가 동시에 접근하도록 설계돼 있지 않으므로 클러스터 파일시스템을 써야 합니다. 즉 Multi-Attach는 "EBS를 공유 스토리지로 쓰는 기능"이 아니라 **클러스터 소프트웨어가 이미 있을 때 쓰는 기능**입니다 ([EBS Multi-Attach](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-volumes-multi.html)).

EFS는 여러 AZ의 여러 인스턴스가 동시에 읽고 쓰는 것이 기본 동작입니다. S3는 리전 엔드포인트라서 네트워크가 닿는 곳이면 어디서든 접근합니다 — Lambda, 다른 계정, 브라우저까지.

### 2-2. AZ 경계 — 장애 단위가 어디까지인가

EBS 볼륨은 AZ에 묶입니다. 그 AZ가 죽으면 볼륨도 못 씁니다. 다른 AZ로 옮기려면 스냅샷을 떠서 복원하는 수밖에 없습니다.

EFS Regional과 S3(일반 버킷)는 여러 AZ에 걸쳐 저장됩니다. 단, EFS One Zone과 S3 One Zone-IA는 이름 그대로 한 AZ에만 있으므로 같은 전제가 아닙니다.

### 2-3. 수명 — 누가 먼저 죽는가

인스턴스보다 데이터가 오래 살아야 하면 EBS 로컬 경로는 후보에서 빠집니다. 오토스케일링 그룹이 인스턴스를 교체하는 건 장애가 아니라 **정상 동작**입니다.

판단 기준은 간단합니다. "이 인스턴스를 지금 종료해도 괜찮은가"에 아니라고 답한다면, 그 데이터는 인스턴스 밖에 있어야 합니다.

### 2-4. 과금 단위 — 무엇을 세는가

여기서 설계가 가장 많이 틀립니다. 셋은 **세는 대상 자체가** 다릅니다.

- **EBS는 프로비저닝한 용량을 셉니다.** 100GiB 볼륨에 1GiB만 썼어도 100GiB 요금입니다. gp3는 GB-월 $0.08이고, 기본 3,000 IOPS와 125MiB/s가 포함됩니다. 그 위로는 IOPS당 $0.005/월, 처리량 MB/s당 $0.06/월이 따로 붙습니다. 스냅샷은 Standard 기준 GB-월 $0.05입니다 ([EBS 요금](https://aws.amazon.com/ebs/pricing/), 리전은 페이지에서 확인해야 합니다).
- **EFS는 실제 저장량 + 읽고 쓴 양을 셉니다.** Elastic 처리량 모드에서는 프로비저닝 없이 "읽고 쓴 메타데이터와 데이터의 양"만 과금합니다.
- **S3는 저장량 + 요청 건수를 셉니다.** S3 Standard의 GET 요청은 1,000건당 $0.0004입니다 ([S3 요금](https://aws.amazon.com/s3/pricing/)).

그래서 "용량당 단가"만 비교하면 결론이 틀립니다. 작은 파일 수억 개는 요청 과금이 저장 과금을 넘어서고, 큰 파일 몇 개는 그 반대입니다.

---

## 3. 성능은 같은 축에서 비교되지 않습니다

세 서비스의 지연 시간은 자리수가 다릅니다. 이걸 알면 "S3로 바꾸면 느려지지 않나" 같은 질문에 숫자로 답할 수 있습니다.

| | 지연(첫 바이트) | 처리량 상한 |
|---|---|---|
| EBS gp3 | 한 자리 밀리초 | 125MiB/s 기본, 최대 2,000MiB/s |
| EFS Standard | 읽기 약 1ms, 쓰기 약 2.7ms (최적 조건) | 클라이언트 1대당 1,500MiB/s |
| S3 Standard | 대략 100~200ms | 인스턴스 네트워크 대역폭까지 (단일 인스턴스 최대 100Gb/s 사례) |

출처: [EBS gp3](https://docs.aws.amazon.com/ebs/latest/userguide/general-purpose.html), [EFS 성능 사양](https://docs.aws.amazon.com/efs/latest/ug/performance.html), [S3 성능 설계 패턴](https://docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance.html).

읽어야 할 점 세 가지입니다.

1. **gp3는 버스트가 없습니다.** gp2처럼 크레딧을 쌓아서 튀어오르지 않고, 프로비저닝한 성능을 계속 유지합니다. 뒤집으면 125MiB/s로 부족하면 **직접 올려야** 하고, 안 올리면 영원히 125MiB/s입니다. gp3의 IOPS 상한은 80,000(GiB당 500 IOPS 비율), 처리량 상한은 2,000MiB/s(프로비저닝 IOPS당 0.25MiB/s 비율)입니다.
2. **EFS의 병목은 파일시스템이 아니라 클라이언트일 수 있습니다.** 파일시스템 전체로는 읽기 20~60GiBps가 나오지만, 클라이언트 1대가 끌어낼 수 있는 건 1,500MiB/s입니다. 그것도 Elastic 모드 + EFS 클라이언트 2.0 이상 조건이고, 그 밖의 조합은 **500MiBps**입니다. EC2 1대에서 돌리는 배치가 안 빨라지는 이유가 여기 있는 경우가 많습니다.
3. **S3의 100~200ms는 "요청 1건당"입니다.** 병렬로 때리면 전체 처리량은 올라갑니다. 즉 S3는 **대역폭은 좋고 지연은 나쁜** 저장소입니다. 요청마다 S3를 한 번 왕복하는 동기 API 경로에 끼워 넣으면 그 지연이 응답 시간에 그대로 더해집니다.

### 3-1. EFS를 골랐다면 처리량 모드가 두 번째 선택입니다

EFS를 고른 뒤에도 선택이 하나 남습니다. 처리량 모드 세 개 — Elastic, Provisioned, Bursting — 중 무엇을 쓸지입니다. 기본값은 Elastic이고, AWS도 Elastic을 권장합니다.

판단 기준이 문서에 숫자로 나와 있습니다. **평균 대비 피크 비율(average-to-peak ratio)이 5% 이하**면 Elastic, 5% 이상이면 Provisioned입니다 ([EFS 성능 사양](https://docs.aws.amazon.com/efs/latest/ug/performance.html)). 하루에 몇 번 몰아서 쓰는 배치라면 Elastic이고, 하루 종일 꾸준히 쓰는 워크로드라면 Provisioned가 싸진다는 뜻입니다.

Bursting은 처리량이 **저장 용량에 비례**하는 모드입니다. Standard 스토리지 GiB당 50KiBps가 기준선이고, 그 아래로 쓰면 크레딧이 쌓이고 넘겨 쓰면 깎입니다. 문제는 신규 서비스입니다. 데이터가 10GiB뿐이면 기준선은 500KiBps입니다. 크레딧이 떨어지면 거기까지 내려앉습니다. 저장한 데이터가 적을 때 가장 느려지는 모드라서, 크레딧을 다 쓰거나 허용 처리량의 80%를 넘게 쓰고 있다면 Elastic이나 Provisioned로 옮기라고 문서가 직접 권합니다.

모드 변경에는 제약이 하나 있습니다. Provisioned로 바꾸거나 프로비저닝 양을 바꾸면 **24시간 동안** 다시 Elastic/Bursting으로 되돌리거나 양을 줄이는 것이 막힙니다. 올리는 건 언제든 되지만 내리는 건 하루 기다려야 합니다. 부하 테스트하면서 값을 왔다갔다 조정할 생각이라면 이걸 먼저 알아야 합니다.

---

## 4. 코드로 보는 차이

### 4-1. 로컬 경로에 저장 ❌

```java
@Service
public class ProfileImageService {

    private static final Path UPLOAD_DIR = Path.of("/var/app/uploads");

    public String store(MultipartFile file, Long memberId) throws IOException {
        String fileName = memberId + "-" + UUID.randomUUID() + ".jpg";
        Path target = UPLOAD_DIR.resolve(fileName);
        file.transferTo(target);
        return "/uploads/" + fileName;   // 이 인스턴스에서만 유효한 경로
    }
}
```

문제는 코드가 아니라 전제입니다. 이 코드는 "요청을 처리한 인스턴스가 나중에 그 파일을 다시 서빙한다"를 가정합니다. ALB 뒤에 2대가 있으면 그 가정이 깨집니다. 업로드는 1번 인스턴스가 받고 조회는 2번 인스턴스로 가면 404입니다.

### 4-2. S3에 저장하고, 조회는 presigned URL로 ✔️

```java
@Service
public class ProfileImageService {

    private final S3Client s3;
    private final S3Presigner presigner;
    private final String bucket;   // application.yml에서 주입

    public ProfileImageService(S3Client s3, S3Presigner presigner,
                               @Value("${app.image-bucket}") String bucket) {
        this.s3 = s3;
        this.presigner = presigner;
        this.bucket = bucket;
    }

    public String store(MultipartFile file, Long memberId) throws IOException {
        String key = "profile/%d/%s.jpg".formatted(memberId, UUID.randomUUID());
        s3.putObject(
                PutObjectRequest.builder()
                        .bucket(bucket)
                        .key(key)
                        .contentType(file.getContentType())
                        .build(),
                RequestBody.fromInputStream(file.getInputStream(), file.getSize()));
        return key;   // DB에는 key만 저장합니다
    }

    public URL presignedUrl(String key) {
        GetObjectPresignRequest request = GetObjectPresignRequest.builder()
                .signatureDuration(Duration.ofMinutes(10))
                .getObjectRequest(b -> b.bucket(bucket).key(key))
                .build();
        return presigner.presignGetObject(request).url();
    }
}
```

바뀐 건 저장 위치만이 아닙니다. **파일 바이트가 애플리케이션 서버를 통과하지 않게** 됐습니다. 조회 트래픽이 S3로 직접 가므로 애플리케이션은 URL만 발급합니다. DB에 전체 URL이 아니라 `key`만 저장하는 것도 의도입니다 — 버킷을 옮기거나 CloudFront를 앞에 붙일 때 DB를 마이그레이션하지 않아도 됩니다.

### 4-3. 그래서 흐름이 이렇게 바뀝니다

```
기존:  브라우저 → ALB → EC2(로컬 디스크 저장) → EC2가 직접 서빙
개선:  브라우저 → ALB → EC2(S3 PutObject) → DB에 key 저장
       조회:  브라우저 → ALB → EC2(presigned URL 발급) → 브라우저 → S3
```

---

## 5. 고르는 순서

위에서부터 내려오면서 처음으로 "예"가 나오는 곳에서 멈춥니다.

1. **블록 디바이스가 필요한가?** — DB 데이터 파일, 부팅 볼륨, 스왑. → **EBS**. RDS를 쓴다면 이건 AWS가 알아서 합니다(day46-rds-basics.md).
2. **기존 코드가 POSIX 파일시스템을 요구하고, 고칠 수 없는가?** — `File` API를 쓰는 레거시, 파일 락, 디렉터리 순회, 상용 솔루션의 작업 디렉터리. 그런데 여러 대가 공유해야 합니다. → **EFS**.
3. **여러 대가 공유해야 하고 코드를 고칠 수 있는가?** → **S3**. 업로드 파일, 이미지, 리포트, 로그 아카이브, 백업은 거의 전부 여기입니다.
4. **한 대만 쓰고, 인스턴스와 함께 사라져도 되는가?** — 임시 파일, 캐시, 빌드 산출물. → **EBS(또는 인스턴스 스토어)**.

2번이 함정입니다. "공유 파일시스템이 필요하다"는 요구사항은 대개 요구사항이 아니라 **기존 코드의 형태**입니다. 신규 설계에서 2번이 나왔다면 한 번 더 의심하세요. EFS는 "S3로 리팩터링할 수 없을 때 지불하는 비용"에 가깝습니다.

---

## 6. 함정

### 6-1. EBS는 아무 데도 안 붙어 있어도 과금됩니다

- **증상**: 인스턴스를 다 지웠는데 EBS 요금이 계속 나옵니다.
- **원인**: EBS는 "프로비저닝한 용량"을 과금합니다. 인스턴스를 종료할 때 `DeleteOnTermination`이 꺼진 볼륨은 그대로 남고, available 상태로 떠 있어도 100% 요금이 붙습니다. 스냅샷도 따로 과금됩니다(Standard GB-월 $0.05).
- **해법**: `available` 상태 볼륨과 어떤 AMI도 참조하지 않는 오래된 스냅샷을 주기적으로 찾아내 지웁니다. 비용 구조 전반은 day58-cloud-cost-basics.md를 참고하세요.

### 6-2. EFS를 다른 AZ에서 마운트하면 GB당 요금이 붙습니다

- **증상**: EFS 저장 용량은 작은데 데이터 전송 요금이 저장 요금보다 큽니다.
- **원인**: AZ를 넘어 마운트 타깃에 접근하면 들어오고 나가는 데이터에 **GB당 $0.01**이 붙습니다 ([EFS 요금](https://aws.amazon.com/efs/pricing/)). AZ 3개에 인스턴스를 깔고 마운트 타깃은 1개만 만들어 두면 트래픽의 2/3가 과금 대상이 됩니다.
- **해법**: 인스턴스가 있는 **모든 AZ에 마운트 타깃을 만듭니다.** 마운트 타깃 자체에는 시간 요금이 없으므로 안 만들 이유가 없습니다.

### 6-3. EFS에 작은 파일을 수백만 개 두면 처리량이 안 나옵니다

- **증상**: 네트워크도 CPU도 한가한데 파일 순회가 느립니다.
- **원인**: EFS는 모든 NFS 요청을 **4KB 또는 실제 요청/응답 크기 중 큰 쪽**으로 처리량 과금에 계산합니다 ([EFS 성능 사양](https://docs.aws.amazon.com/efs/latest/ug/performance.html)). 1KB 파일 100만 개를 읽으면 1GB가 아니라 4GB로 계산됩니다. 거기에 파일 하나마다 네트워크 왕복이 생깁니다. 로컬 디스크에서 1초 걸리던 `listFiles()`가 EFS에서 분 단위가 되는 이유입니다.
- **해법**: 작은 파일을 많이 다루는 워크로드는 애초에 EFS에 올리지 않습니다. 묶어서 저장하거나 S3로 옮깁니다. 이미 EFS라면 디렉터리 순회를 없애고 목록을 DB에 들고 갑니다.

### 6-4. EFS 라이프사이클이 조용히 지연을 바꿉니다

- **증상**: 몇 달 잘 돌던 배치가 어느 날부터 느려집니다. 설정은 안 바꿨습니다.
- **원인**: 기본 라이프사이클 정책이 켜져 있습니다. Standard에서 30일간 접근이 없으면 IA로, 90일간 없으면 Archive로 전환됩니다 ([EFS 스토리지 라이프사이클](https://docs.aws.amazon.com/efs/latest/ug/lifecycle-management-efs.html)). Standard의 첫 바이트 지연은 읽기 약 1ms인데, IA와 Archive는 **수십 ms**입니다. 저장 비용은 줄었지만 오래된 파일을 긁는 월간 배치는 그만큼 느려집니다.
- **해법**: 접근 빈도가 낮지만 **지연에 민감한** 파일이 있으면 라이프사이클 정책을 조정합니다. 전환이 비용 절감 장치라는 걸 알고 켜는 것과, 켜져 있는 걸 모르는 것은 다릅니다.

### 6-5. S3를 파일시스템처럼 쓰면 깨집니다

- **증상**: 로그를 S3 객체에 이어붙이려 했더니 방법이 없습니다. 두 서버가 같은 키에 쓰면 한쪽 내용이 사라집니다.
- **원인**: S3에는 부분 쓰기와 append가 없습니다. 객체 갱신은 **통째로 다시 올리는 PUT**입니다. 그리고 S3는 동시 쓰기를 위한 객체 락을 제공하지 않습니다. 같은 키에 PUT 두 개가 동시에 들어오면 타임스탬프가 늦은 쪽이 이깁니다 ([S3 데이터 일관성 모델](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html)). 키 하나의 갱신은 원자적이라 깨진 데이터를 읽는 일은 없지만, **키 여러 개에 걸친 원자적 갱신은 불가능**합니다.
- **해법**: 추가되는 데이터는 객체를 수정하지 않고 **새 키로 씁니다**(`logs/2026-10-27/{uuid}.json`). 여러 키를 묶어야 하는 상태는 S3가 아니라 DB에 둡니다. 읽은 뒤 쓰는 갱신이 필요하면 조건부 쓰기나 별도 락이 필요합니다.

### 6-6. S3에서 503 Slow Down이 뜹니다

- **증상**: 트래픽을 갑자기 올린 직후 `503 (Slow Down)`이 섞여 나옵니다.
- **원인**: S3는 **파티션된 prefix 하나당** 최소 3,500 PUT/COPY/POST/DELETE, 5,500 GET/HEAD를 보장합니다. 그 위로도 자동 확장되지만 **점진적으로** 일어나고, 확장되는 동안 503이 보일 수 있습니다 ([S3 성능 설계 패턴](https://docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance.html)).
- **해법**: 버킷의 prefix 개수에는 제한이 없습니다. 키를 여러 prefix로 쪼개 병렬화합니다. prefix 10개면 읽기를 초당 55,000까지 올릴 수 있습니다. 모든 키를 `uploads/` 하나에 몰아넣는 설계가 가장 나쁩니다. 그리고 503은 재시도 대상이므로 SDK의 백오프 재시도를 끄지 않습니다.

### 6-7. S3 Standard-IA로 내렸는데 요금이 안 줄어듭니다

- **증상**: 라이프사이클로 오래된 썸네일을 Standard-IA로 전환했는데 절감액이 계산한 것의 절반도 안 됩니다.
- **원인**: Standard-IA에는 **최소 과금 객체 크기 128KB**와 **최소 저장 기간 30일**이 있습니다 ([S3 요금](https://aws.amazon.com/s3/pricing/)). 10KB 썸네일도 128KB로 과금됩니다. 저장은 되지만 청구는 13배로 올라가므로, 작은 객체는 IA로 내리는 순간 오히려 비싸집니다. 30일 전에 지우면 남은 일수가 일할 계산으로 청구됩니다.
- **해법**: 라이프사이클 규칙에 객체 크기 필터를 걸어 작은 객체는 Standard에 남깁니다. 수명이 30일 미만인 객체는 전환 대상에서 빼고 만료 규칙만 둡니다.

---

## 7. 한 장 요약

| 기준 | EBS | EFS | S3 |
|---|---|---|---|
| 인터페이스 | 블록 | NFS(POSIX) | HTTP API |
| 동시 접근 | 1대 (Multi-Attach는 조건부) | 여러 대·여러 AZ | 어디서나 |
| AZ 경계 | AZ에 고정 | Regional은 다중 AZ | 다중 AZ |
| append | 파일시스템이 지원 | 지원 | 없음 |
| 과금 | 프로비저닝 용량 | 저장량 + 읽고 쓴 양 | 저장량 + 요청 수 |
| 전형적 용도 | 부팅 볼륨, DB 데이터 파일 | 공유 작업 디렉터리, 레거시 | 업로드 파일, 아카이브, 백업 |

고민이 길어지면 2-1(공유 범위)과 2-3(수명)으로 돌아갑니다. 이 두 축에서 답이 안 나오는 경우는 드뭅니다.

---

## 8. 참고자료

- [Amazon EBS General Purpose SSD volumes](https://docs.aws.amazon.com/ebs/latest/userguide/general-purpose.html) — gp3 기본·상한 성능, gp2 버스트 크레딧
- [Attach an EBS volume to multiple EC2 instances using Multi-Attach](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-volumes-multi.html) — Multi-Attach 제약
- [Amazon EFS performance specifications](https://docs.aws.amazon.com/efs/latest/ug/performance.html) — 지연, 처리량 모드, 4KB 메트링
- [Managing storage lifecycle (EFS)](https://docs.aws.amazon.com/efs/latest/ug/lifecycle-management-efs.html) — IA·Archive 전환 기본값
- [What is Amazon S3? — 데이터 일관성 모델](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html)
- [Best practices design patterns: optimizing Amazon S3 performance](https://docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance.html)
- 요금: [EBS](https://aws.amazon.com/ebs/pricing/) · [EFS](https://aws.amazon.com/efs/pricing/) · [S3](https://aws.amazon.com/s3/pricing/)

<!-- TODO: 확인 필요 — EFS Standard/IA/Archive의 GB-월 단가는 공식 요금 페이지에서 지역별 표를 추출하지 못해 본문에 숫자를 넣지 않았습니다. EBS·S3 단가도 공식 페이지에 리전 표기가 없는 값이라, 실제 견적은 리전을 지정해 AWS Pricing Calculator로 다시 확인해야 합니다. -->
