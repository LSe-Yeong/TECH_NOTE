# 인덱스는 어떻게 빠른가

## 1. 핵심 개념: B-Tree(B+Tree)란 무엇인가

- `00-why-index`에서 인덱스가 있으면 빠르다고 했는데, 그 안에서 실제로 쓰이는 자료구조가 **B-Tree**(정확히는 대부분 **B+Tree**)입니다.
- B+Tree는 값을 정렬된 상태로 유지하는 **균형 트리**입니다. 모든 리프 노드가 같은 깊이에 있습니다.
- 이 구조 덕분에 탐색 비용이 데이터 전체를 읽는 것(`O(n)`)이 아니라 트리 깊이에 비례하는 수준(`O(log n)`)으로 줄어듭니다.

> **인덱스가 왜 빠른지 모르면 "인덱스를 걸었는데 왜 여전히 느리지?"라는 질문에 답을 못 합니다.** 특히 세컨더리 인덱스를 타고 있는데도 느린 경우가 대표적입니다.

## 2. 구조

- **내부 노드**: 키 값과 자식 노드를 가리키는 포인터만 저장합니다. 트리를 타고 내려가는 이정표 역할입니다.
- **리프 노드**: 클러스터드 인덱스(PK 기준)라면 실제 행 데이터 전체를, 세컨더리 인덱스라면 PK 값만 저장합니다.
- 모든 리프 노드가 같은 깊이에 있어서, 어떤 값을 찾든 탐색 횟수가 일정합니다. 최악의 경우도 예측 가능합니다.
- 리프 노드끼리 양방향으로 연결돼 있어서, 범위 조건(`BETWEEN`, `>`)이나 정렬(`ORDER BY`)을 리프를 따라가며 순차 처리할 수 있습니다.

### 2-1. 선택적 확장 지점

- 기본은 B+Tree입니다.
- MySQL의 MEMORY 스토리지 엔진은 인덱스 타입을 `HASH`로 선택할 수 있습니다. 등치 비교만 필요하고 데이터가 메모리에 전부 올라가는 임시성 테이블 등에서 선택적으로 씁니다.

## 3. 흐름

### 3-1. 탐색 과정

```
루트 노드 (키 범위로 자식 결정)
  → 내부 노드 (키 범위로 자식 결정)
    → 리프 노드 (실제 데이터 또는 PK)
      → (다음 리프로, 범위 검색 시) 다음 리프 노드
```

### 3-2. 비교 횟수

```
행 N개가 저장된 테이블
풀 테이블 스캔: 최악의 경우 N번 비교 — 데이터가 늘수록 비례해서 늘어남
B+Tree 탐색:   트리 깊이만큼만 이동 — 데이터가 늘어도 깊이는 완만하게(log N에 비례) 늘어남
```

## 4. 특징

### 4-1. 사용 시기

- 범위 검색(`>`, `<`, `BETWEEN`)이나 정렬(`ORDER BY`)이 필요한 대부분의 실무 상황. 사실상 기본 선택지입니다.

### 4-2. 장점

- 균형 트리라서 최악의 경우도 `O(log n)`으로 보장됩니다.
- 정렬된 상태를 유지하기 때문에 범위 검색과 정렬을 자연스럽게 지원합니다.

### 4-3. 단점 / 트레이드오프

- 삽입·삭제할 때 트리의 균형을 유지하기 위한 재조정(페이지 분할·병합) 비용이 있습니다.
- 등치 비교(`=`) 하나만 놓고 보면, 트리를 타고 내려가야 하는 B-Tree가 Hash 인덱스보다 느립니다.

## 5. 예제: 세컨더리 인덱스가 왜 두 번 순회하는가

### 5-1. 클린하지 않은 코드 ❌

```sql
-- ❌ status는 세컨더리 인덱스지만, SELECT *라서 인덱스에 없는 컬럼까지 필요하다
-- → 세컨더리 인덱스에서 PK를 찾은 뒤, 클러스터드 인덱스를 다시 조회해야 한다 (두 번 순회)
CREATE INDEX idx_orders_status ON orders (status);

SELECT * FROM orders WHERE status = 'PENDING';
```

### 5-2. 커버링 인덱스를 적용한 코드 ✔️

```sql
-- ✅ 필요한 컬럼(status, id)을 인덱스 자체에 포함시키면 클러스터드 인덱스를 다시 조회할 필요가 없다
CREATE INDEX idx_orders_status_covering ON orders (status, id);

SELECT id FROM orders WHERE status = 'PENDING';
```

## 6. 정렬 순서 유지 원칙

- B-Tree는 값을 정렬된 순서로 유지하기 때문에 범위 검색이 가능합니다. Hash는 값을 해시값으로 흩어놓기 때문에 순서 개념 자체가 없습니다.

### 6-1. 원칙이 성립하지 않는 코드 ❌

```sql
-- ❌ HASH 인덱스는 등치 비교만 지원한다
CREATE TABLE session_cache (
    token VARCHAR(64),
    created_at DATETIME,
    INDEX USING HASH (token)
) ENGINE=MEMORY;

SELECT * FROM session_cache WHERE created_at > '2026-01-01';
-- created_at에는 인덱스가 없고, 있었다 해도 HASH라면 범위 검색에 못 쓰인다
```

### 6-2. 원칙이 성립하는 코드 ✔️

```sql
-- ✅ B-Tree(기본값) 인덱스는 정렬 순서를 유지하므로 범위 검색을 그대로 지원한다
CREATE TABLE session_cache (
    token VARCHAR(64),
    created_at DATETIME,
    INDEX (created_at)
) ENGINE=InnoDB;

SELECT * FROM session_cache WHERE created_at > '2026-01-01';
```

## 7. 확장 지점 응용하기 — USING HASH

### 7-1. 클린하지 않은 코드 ❌

```sql
-- ❌ 세션 토큰처럼 항상 "=" 비교만 하는 컬럼에 기본값(B-Tree)을 그대로 쓴다
CREATE TABLE session_cache (
    token VARCHAR(64),
    user_id BIGINT,
    INDEX (token)
) ENGINE=MEMORY;
```

### 7-2. HASH를 명시한 코드 ✔️

```sql
-- ✅ 등치 비교만 필요하다는 걸 알고 있다면 HASH를 명시해 더 빠른 조회를 얻는다
CREATE TABLE session_cache (
    token VARCHAR(64),
    user_id BIGINT,
    INDEX USING HASH (token)
) ENGINE=MEMORY;

SELECT user_id FROM session_cache WHERE token = 'abc123';
```

## 8. 실무에서 찾아보는 인덱스 구조

- InnoDB **Adaptive Hash Index(AHI)** — 자주 조회되는 페이지를 InnoDB가 자동으로 감지해서, 내부적으로 해시 인덱스를 추가로 만들어주는 기능입니다. `innodb_adaptive_hash_index` 설정으로 켜고 끌 수 있습니다.

## 9. 관련된 개념과 비교

### 9-1. B-Tree VS Hash 인덱스

**유사점**

- 둘 다 탐색 비용을 줄인다는 목적은 같습니다.

**차이점**

- B-Tree는 `O(log n)`이고, 등치·범위·정렬을 모두 지원합니다.
- Hash는 평균 `O(1)`이지만 등치 비교만 지원하고, 범위 검색이나 정렬에는 쓸 수 없습니다.
- 그래서 대부분의 DB는 B-Tree를 기본값으로 쓰고, Hash는 등치 비교만 필요한 특수한 상황(캐시성 테이블 등)에서 선택적으로 씁니다.

## 10. 함정

**세컨더리 인덱스를 탔는데도 쿼리가 느리다**

- **증상**: `EXPLAIN`에서 인덱스를 사용한다고 나오는데도 응답이 느립니다.
- **원인**: 세컨더리 인덱스는 리프에 PK 값만 저장합니다. 인덱스에 없는 컬럼을 조회하면 그 PK로 클러스터드 인덱스를 다시 찾아가야 합니다(두 번 순회). 조회 대상 행이 많을수록 이 추가 조회 비용이 커집니다.
- **해법**: 자주 쓰는 `SELECT` 컬럼을 인덱스에 포함시켜(커버링 인덱스) 추가 조회를 없앱니다. (5장 참고)

**HASH 인덱스 컬럼에 범위 검색을 걸었더니 인덱스를 안 탄다**

- **증상**: `WHERE created_at > '...'` 같은 조건에서 `EXPLAIN`을 보면 인덱스를 못 타고 풀 스캔이 나옵니다.
- **원인**: HASH 인덱스는 값을 해시로 흩어놓기 때문에 순서 정보가 없어 범위 검색을 지원하지 않습니다.
- **해법**: 범위 검색이나 정렬이 필요한 컬럼에는 HASH가 아니라 B-Tree(기본값)를 씁니다.

## 11. 참고자료

- [MySQL 8.0 Reference Manual — Clustered and Secondary Indexes](https://dev.mysql.com/doc/refman/8.0/en/innodb-index-types.html)
- [MySQL 8.0 Reference Manual — Comparison of B-Tree and Hash Indexes](https://dev.mysql.com/doc/refman/8.0/en/index-btree-hash.html)
- `daily/day05-why-index.md` — 인덱스 없는 테이블은 왜 느린가
- `07-database/05-index-not-used` — 인덱스가 있는데 안 타는 경우들
