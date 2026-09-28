# HANDOFF — Wireless Limitless (QCY 이어버드 PC 컨트롤러)

> 이 문서는 Claude Code ↔ Codex 사이의 작업 인계용 자기완결 브리프입니다.
> 채팅 기록을 볼 수 없다는 전제로 작성되었으며, 이 문서만 읽고 작업을 이어받을 수 있어야 합니다.
> 코드나 진행 상황이 바뀌면 **6. 현재 상태**와 관련 항목을 반드시 함께 갱신하세요.

---

## 1. 프로젝트 개요와 목표

Windows PC에서 **QCY 무선 이어버드(1차 대상: QCY HT08 MeloBuds Pro Plus)** 의 설정을
QCY 공식 안드로이드 앱과 동등하게 제어하는 데스크톱 앱. 노이즈 캔슬링(ANC)·이퀄라이저(EQ)·터치 조작·
각종 기기 설정을 BLE(GATT)로 직접 제어하며, 로컬 서버 없이 PC 안에서 단독 실행되고,
GitHub 릴리즈 기반으로 스스로 업데이트한다.

- 앱 표시 이름: **Wireless Limitless** (프로젝트 폴더명 `wireless limitless`에서 따옴 — 바꾸려면 `src/wireless_limitless/config.py`와 빌드/설치 스크립트의 이름만 수정)
- 실행 파일: `WirelessLimitless.exe` (PyInstaller onedir)

---

## 2. 사용자 요구사항 (원문 의도 보존)

### 2-1. 채팅에서 받은 요구 (원문 + 결정)
1. 기능 요구 원문:
   > "지금 블루투스로 연결되어있는 qcy 모델의 기능을 제어하는 pc 용 앱을 만들어줘. 노이즈 캔슬링, 이퀄라이저 등등 qcy 안드로이드에서 제공하는 모든 기능을 사용할 수 있게"
   - 대상 기기 = 요청 시점에 PC와 연결돼 있던 **QCY HT08 MeloBuds Pro Plus** (펌웨어 L/R 2.0.7).
   - "공식 앱의 모든 기능" = QCY 서버가 이 모델(vendorId 19790)에 내려주는 제어 패널 정의 전체 + 공식 앱 설정 화면에서 캡처로 확인된 항목 → **3-4 기능 패리티 표**.
   - **의도적 제외: 펌웨어 OTA 업데이트** (프로토콜 비공개, 실패 시 벽돌 위험). 앱은 펌웨어 버전만 보여 주고 "펌웨어 업데이트는 QCY 앱에서"라고 안내.
2. UI 스타일 선택 (3개 후보 A Aurora 다크 글래스 / B Fluent Windows 11 라이트 / C Studio 앰버 하이파이 중):
   > "b 인데 조금더 둥글둥글하게 바꿔주라. 폰트도 그러고, 부가설명도 줄여주고"
   - 결과: **"Soft Fluent"** — B를 기반으로 모서리를 크게(카드 26px, 칩·세그먼트·버튼은 pill), 둥근 한글 폰트 **나눔스퀘어라운드**(OFL, woff2 번들), 항목별 설명 문장을 대부분 제거하거나 2~5단어로 축약(장면 설명은 툴팁으로 이동).
   - 후보 원본은 `design/style-A-aurora.html`, `style-B-fluent.html`, `style-C-studio.html`(+ `design/shots/style-*.png`)로 보존.
3. GitHub: **공개 저장소 `jykim5215/wireless-limitless` 새로 만들기 승인**. 단, 실제 push/Release 직전에 올릴 내용을 다시 확인받는다.
4. 실기기 쓰기 테스트 허용 범위: **"소음 제어·EQ·설정 전환" (테스트 후 원래 값 복원)**. "이어버드 찾기" 소리 테스트는 **허용되지 않음**.

### 2-2. 사용자의 앱 제작 프로세스 규칙 (모든 작업에 항상 적용)
1. **배포용 압축파일 + 보안 점검**: 앱 파일을 만들 때마다 배포 zip을 함께 만든다. zip에는 이 PC에서 실험하며 생긴 개인정보(블루투스 주소, 사용자 경로, 로그 등)를 넣지 않고 보안 점검 결과(`SECURITY.md`)를 포함한다. 결과 보고 끝에 "개선한 취약점(없으면 없음)"을 적는다.
2. **UI/UX**: 말한 대로만 만들지 말고 실제 사용자 시뮬레이션으로 구획/통합을 스스로 결정, 중복 기능은 통합. **스타일 후보 3개 이상을 HTML로 보여 주고 사용자가 반드시 선택**.
3. **디바이스 내 구동**: 로컬 서버 방식 금지. 언제 실행해도 정상 동작.
4. **원클릭 바로가기**: 주제 관련 아이콘으로 바탕화면/시작 메뉴 바로가기.
5. **GitHub 릴리즈 기반 자체 업데이트**: 루트 `version.json`(`{"version","changelog"}`, semver) 관리·코드 수정 시 버전 갱신. 배포 zip마다 커밋 + Release(태그, `version.json`·zip 첨부). push/release 전 사용자 확인. 앱 내 업데이트 확인(시작 시 자동 + 버튼) → changelog 표시 → 승인 시 교체. 네트워크 실패 시 에러만 표시. 토큰 하드코딩 금지.
6. **HANDOFF.md**: 코드 작성 전에 먼저 작성, 진행 때마다 갱신, 배포 패키지에도 포함.

---

## 3. 기술 방향

### 3-1. 스택
| 영역 | 선택 | 이유 |
|---|---|---|
| 언어/런타임 | Python 3.14 (PyInstaller 번들 → 사용자 PC에 파이썬 불필요) | BLE·GUI·패키징이 이 PC에서 검증됨 |
| BLE | `bleak` 3.0.2 (WinRT) | Windows 네이티브 GATT. 페어링 없이 연결/읽기/쓰기 검증 완료 |
| UI | `pywebview` 6.2.1 (WebView2) + 로컬 HTML/CSS/JS, 폰트 나눔스퀘어라운드 | `file:///` 절대 URL로 로드 → pywebview 내장 HTTP 서버 미기동(상대경로일 때만 서버를 띄움) |
| JS↔Python | pywebview `js_api` 브리지, Python→JS는 `window.run_js` | 소켓/포트 없음 |
| 패키징 | PyInstaller 6.22.3 onedir | 시작이 빠르고 자체 업데이트 시 폴더 교체가 쉬움 |
| 테스트 | pytest(58개) + 실기기 스크립트 2종 | |

### 3-2. 아키텍처 / 스레드 모델
```
[Main thread] pywebview GUI loop (WebView2)
      │ js_api 호출(pywebview 워커 스레드)            ▲ run_js("WL.onState(json)")  ← StatePusher(30ms 합치기)
      ▼                                             │
[bridge.Bridge] ── run_coroutine_threadsafe ──► [runner.LoopThread: asyncio loop "ble-loop"]
                                                   DeviceController (controller.py)
                                                     ├─ QcyTransport (transport.py, bleak)
                                                     ├─ protocol.py  (순수: 프레임/명령/파서)
                                                     └─ catalog.py   (모델 기능표·EQ 프리셋)
[updater.py] urllib → GitHub API (확인/다운로드 때만) → 검증 → cmd 헬퍼로 교체
```
- 모든 BLE 작업은 단일 asyncio 루프 + `asyncio.Lock`으로 직렬화.
- 슬라이더/EQ 입력은 `_coalesce()`로 "최신 값만" 전송(EQ 147바이트 프레임은 0.6초 간격), 끝나면 1회 재조회. `flush()`는 대기 중 전송을 마무리(앱 종료 시 자동 호출).
- 연결 관리자(`_manager`)가 끊김 시 3/5/8/12초 백오프로 재스캔·재연결. 30초마다 배터리·ANC 가벼운 폴링, 창 포커스 시에도 새로고침.
- 상태(`DeviceState` dict)는 50ms 이내로 UI에 푸시. UI는 상태만 렌더링하는 단방향 구조.

### 3-3. 검증된 BLE 프로토콜 (실기기 HT08 MeloBuds Pro Plus, 펌웨어 2.0.7)
- **발견**: 광고 manufacturer data, Company ID `0x521C`. payload[0..1] = vendorId(big-endian): `19790` = HT08 MeloBuds Pro Plus, `19786` = MeloBuds Pro(동일 기능표). payload[5..7] = L/R/케이스 배터리(bit7=충전, 하위7bit=%). 케이스는 이 모델에서 항상 0 → "정보 없음" 처리.
  - payload[11..16] = 클래식 BT 주소(바이트 순서: `[12]:[11]:[13]:[16]:[15]:[14]`). BLE 주소는 클래식 주소에서 파생된 랜덤 static 주소. 광고는 간헐적(스캔 최대 12초, 보통 1초 내).
- **GATT**: 서비스 `0000a001-…`만 사용. **서비스 `00007033-…`이 같은 UUID(`1001`/`1002`)를 재사용** → 특성 조회는 반드시 서비스로 필터.
  - `00001001` write-without-response: 명령(0xFF 프레임) / `00001002` notify+read: 응답·이벤트, read 시 설정 묶음(state blob)
  - `00000008` read+notify: 배터리 `[L,R,case]` / `00000007` read: 펌웨어 `[Lmaj,Lmin,Lpat,Rmaj,Rmin,Rpat]`
  - `0000000d` read+wwr: 터치 표(프레임 없음, 20B) / `0000000b`: 구형 EQ(읽기 참고용)
  - MTU 220. 페어링(본딩) 불필요.
- **프레임**: `FF <bodyLen> (<op> <n> <params…>)+`, bodyLen = 전체길이−2.
  - **펌웨어 버그**: state blob의 `0x2C` 블록이 길이 3을 선언하고 실제 4바이트를 담음. **길이 3으로 먼저 해석하면 일부 값 조합(예: ANC=일반)에서 0x01/0x03 블록으로 "정상 파싱"되어 버림** → `parse_state_blob`은 `0x2C,3`이면 4를 먼저 시도하고, 설정용 opcode 화이트리스트(`BLOB_OPS`, 리셋·찾기 등 동작 opcode 제외)로만 검증.
- **조회**: `FF 03 FE 01 <op>` → 같은 op 블록으로 응답 (0x2F/0x30/0x08/0x20/0x2D/0x27/0x44/0x06은 이 모델에서 무응답).

| 기능 | op | 쓰기 파라미터 | 읽기/에코 | 실기기 검증 |
|---|---|---|---|---|
| ANC | `0x17` | `[mode, sub, level]` | 즉시 에코 + 2~6.5초 뒤 `0x28 [01]` | ✅ 5개 장면 |
| 밸런스 | `0x16` | `[0..100]` (50=중앙) | 에코 없음(조회로 확인) | ✅ |
| EQ | `0x22` | `[presetId] + 142B 테이블` | 에코 없음(조회로 확인) | ✅ 프리셋·사용자 지정 |
| 게임 모드 | `0x09` | `01`/`02` | `01/02` | ✅ |
| 수면 모드 | `0x10` | `01`/`02` | `00/01` | ✅ |
| LDAC | `0x23` | `01`/`02` | `00/01` | 읽기만 ✅ (쓰기는 재시작 가능성 때문에 미실행) |
| 듀얼 연결 | `0x24` | `01`/`02` | `00/01` | 읽기만 ✅ (동일 사유) |
| 착용 감지 | `0x2C` | `[wear, 01, ancOnWear]` | `[wear, 01, anc, status]` | ✅ |
| 알림음 볼륨 | `0x1D` | `[level, 00]` (4/6/8/10) | `[level, 0F]` | ✅ |
| 예약 끄기 | `0x14` | `[lo, hi, 00, 00]` 분, `FFFF`=끔 | 동일 | ✅ |
| 연결 끊김 후 끄기 | `0x1F` | `[lo, hi]` 분, `FFFF`=안 끔 | 동일 | ✅ |
| 이름 변경 | `0x18` | UTF-8(≤31B) | 32B null-padded | 읽기만 ✅ (복원 불가라 쓰기 미실행) |
| 기본값 복원 / 공장 초기화 | `0x01` / `0x03` | 없음 | — | ❌ 미실행(파괴적) |
| 이어버드 찾기 | `0x05` | `01` 시작 / `00` 정지 | — | ❌ 미검증(실험적, 60초 자동 정지) |
| 터치 조작 | char `000d` | `[slot, func]` 2바이트 | 20B 표 | ✅ |

- **ANC 장면** (`mode, sub, level`): 일반 `(02,00,00)` / 주변음-음성 강조 `(03,02,00)` / 주변음 레벨 L `(03,01,L)` L=1..6 / 적응형 `(01,05,00)` / 실내 `(01,01,0..2)` / 출퇴근 `(01,02,0..2)` / 시끄러운 곳 `(01,03,0..2)` / 바람 소음 `(01,04,00)`. 공식 앱은 `(03,01,00)`을 음성 강조로 취급.
- **터치 기능 ID**: 00 없음, 01 재생/일시정지, 02 이전, 03 다음, 04 음성 비서, 05 볼륨+, 06 볼륨−, 07 게임 모드, **0B ANC 전환**. 슬롯 7·8(용도 미상)은 건드리지 않음.
- **EQ 테이블(142B)** = `masterGain i16(0.01dB)` + 20슬롯 × `[freq u16, gain i16(0.01dB), Q u16(0.01), type u8]`. 프리셋 ID: 공간음향 `0x0A`, 기본 `01`, 팝 `02`, 헤비 베이스 `03`, 록 `04`, 소프트 `05`, 클래식 `06`, 사용자 지정 `0x80`. 프리셋도 테이블 전체 전송(qcyx 캡처 테이블과 바이트 일치를 테스트로 고정). 사용자 지정: 31…16k Hz 10밴드, ±8dB, Q=1.00, type 0, 나머지 슬롯 `{0,0,0,0xFF}`.

### 3-4. 기능 패리티 표 (공식 앱 ↔ 이 앱)
| 공식 앱 기능 | 이 앱 위치 | 상태 |
|---|---|---|
| 배터리(L/R/케이스) | 사이드바 기기 카드 | ✅ |
| ANC: 노이즈 캔슬링 5장면 + 강도 3단계 | 홈 › 소음 제어 | ✅ |
| ANC: 주변음(음성 강조, 레벨 1~6) / 일반 | 홈 › 소음 제어 | ✅ |
| EQ 프리셋 7종 + 사용자 지정 10밴드 | 홈 › 이퀄라이저(주파수 응답 그래프 포함) | ✅ |
| 좌우 밸런스 | 홈 › 이퀄라이저 하단 | ✅ |
| 게임 모드 | 홈 › 게임 모드 카드 | ✅ |
| 터치 조작(1/2/3회 × L/R, 9개 기능) | 터치 조작 | ✅ |
| 착용 감지(+착용 시 소음 제어 복원), 수면 모드 | 설정 › 착용과 조작 | ✅ |
| 알림음 볼륨 | 설정 › 알림음 볼륨 | ✅ |
| 자동 전원 끄기(예약 / 연결 끊김 후) | 설정 › 자동 전원 끄기 | ✅ |
| LDAC / 듀얼 기기 연결 | 설정 › 연결 (변경 전 확인창) | ✅(쓰기 실기기 미검증) |
| 이어버드 찾기 | 사이드바 기기 카드 | ⚠️ 실험적 |
| 기기 이름 변경 | 설정 › 기기 | ✅(쓰기 실기기 미검증) |
| 기본값 복원 / 공장 초기화 | 설정 › 초기화 (확인창, 공장 초기화는 체크박스 추가) | ✅(실기기 미실행) |
| 펌웨어 버전 | 설정 › 기기 | ✅ |
| 펌웨어 업데이트(OTA) | 설정 › 기기(안내 문구만) | 의도적 제외 |

### 3-5. 폴더 구조
```
wireless limitless/                 ← git 저장소 루트
├─ HANDOFF.md README.md SECURITY.md THIRD_PARTY_NOTICES.md version.json pyproject.toml
├─ requirements.txt / requirements-dev.txt
├─ src/wireless_limitless/
│   ├─ __main__.py / app.py   진입점, 로깅, 단일 인스턴스(뮤텍스), 창 생성
│   ├─ config.py              앱 이름·GitHub 저장소·창 크기
│   ├─ paths.py               개발/프리즈 경로, %APPDATA% 데이터 경로
│   ├─ protocol.py            [순수] 프레임, 명령 빌더, 파서
│   ├─ catalog.py             [순수] 모델 기능표, EQ 프리셋 곡선
│   ├─ transport.py           bleak: 스캔·연결 재시도·A001 특성·notify
│   ├─ controller.py          DeviceController: 상태·명령·확인·재연결·폴링
│   ├─ runner.py              BLE 전용 asyncio 스레드
│   ├─ bridge.py              pywebview js_api + StatePusher
│   ├─ storage.py             settings.json (마지막 기기, 자동 업데이트 확인 여부)
│   ├─ updater.py             GitHub 릴리즈 확인·다운로드·SHA-256·zip-slip 방지·교체 헬퍼
│   └─ ui/                    index.html, app.css, app.js, fonts/(나눔스퀘어라운드 R/B/EB)
├─ assets/                    icon.ico, icon.png, icon-256.png (tools/make_icon.py)
├─ design/                    스타일 후보 3종(HTML/PNG), preview-current.html, shots/app-*.png
├─ packaging/                 install.cmd/ps1, uninstall.cmd/ps1 (배포 패키지에 복사됨)
├─ licenses/                  OFL(나눔스퀘어라운드), MIT(qcyx EQ 테이블)
├─ tools/                     build.ps1, package.py, make_icon.py, make_version_info.py, make_previews.py,
│                             preview_mock.js, entry.py, live_check.py, live_write_test.py
├─ tests/                     test_protocol.py, test_updater.py
└─ build/, release/ (gitignore) PyInstaller 산출물, 배포 zip
```
- git 제외: `.venv/`, `build/`, `release/`, `.claude/`·`skills-lock.json`(사용자 로컬 도구, 로컬 경로 포함).
- 설치 위치: `%LOCALAPPDATA%\Programs\WirelessLimitless\` / 사용자 데이터: `%APPDATA%\WirelessLimitless\` (settings.json, logs\app.log — 주소는 마스킹).

### 3-6. GitHub / 버전 관리
- 저장소: **`jykim5215/wireless-limitless` (public, 생성 승인됨)**. 커밋 작성자 이메일은 GitHub noreply 주소 사용.
- `version.json` 버전 = 태그 `vX.Y.Z` = Release 이름.
- Release 자산: `WirelessLimitless-X.Y.Z-win64.zip`, `…zip.sha256`(`<hex>  <파일명>`), `version.json`.
- 앱 업데이트: `GET /repos/jykim5215/wireless-limitless/releases/latest` → 자산 `version.json` 비교 → changelog 표시 → 승인 → zip 다운로드 → SHA-256 검증 → `%TEMP%\WirelessLimitless-update\stage`에 안전 압축 해제 → `%TEMP%\WirelessLimitless-apply-update.cmd`(숨은 콘솔)가 앱 종료 대기 → 설치 폴더 백업(robocopy /MIR) → 새 파일 미러 → 실패 시 롤백 → 재실행.
- 자동 교체 조건: 실행 폴더 이름이 `WirelessLimitless`이고 `_internal`·exe가 있으며 쓰기 가능(다른 폴더를 /MIR로 지우는 사고 방지).

---

## 4. 구현 계획 (진행 순서 · 설계 결정)

1. ✅ 프로토콜 계층 + 단위 테스트(실기기 캡처 바이트 고정, 식별자는 가짜 값).
2. ✅ transport/controller + 실기기 읽기 점검(`tools/live_check.py`).
3. ✅ UI 스타일 후보 3종 → 사용자 선택(B) + 수정 요청 반영(Soft Fluent).
   - 정보 구조: 자주 쓰는 ANC·EQ·게임 모드는 **홈 한 화면(2열)**, 한 번 설정하면 끝나는 터치 조작은 별도 페이지, 나머지는 **설정** 페이지에 주제별 카드. 배터리·연결 상태·찾기·다시 연결은 사이드바 기기 카드에 한 번만.
   - 중복 통합: 게임 모드는 홈에만(공식 앱은 홈/설정 중복), EQ 프리셋과 사용자 지정은 한 카드(사용자 지정 선택 시 10밴드 편집기 펼침), 전원 타이머 2종은 한 카드, LDAC·듀얼은 "연결" 한 카드, 업데이트 확인은 설정 › 앱에만(사이드바는 버전 표시·업데이트 배지만).
4. ✅ 업데이터, 아이콘(파란 스퀘어클 + 흰 이어버드 + 음파), PyInstaller 빌드, 설치/제거 스크립트, 배포 zip + 개인정보 검사.
5. ✅ 실기기 쓰기 검증(`tools/live_write_test.py`) 16/16 통과, 모든 값 복원 확인.
6. ⏳ 로컬 설치 + 바로가기 → 사용자 확인 후 GitHub 저장소 생성·push·Release v1.0.0.

### 백로그(아이디어)
- 전역 단축키로 ANC 전환, 트레이 아이콘, Windows 시작 시 자동 실행 옵션.
- 사용자 지정 EQ 여러 개 저장(로컬 프로필).
- 이어버드 찾기(0x05) 실기기 검증 후 "실험적" 표시 제거.
- 코드 서명 인증서 확보 시 업데이트 서명 검증 추가.

---

## 5. 제약 조건

- 로컬 HTTP 서버/포트 금지 (pywebview `file:///` URL, `http_server=False`).
- 토큰·비밀번호 하드코딩 금지. 업데이트는 공개 API만.
- 배포 zip/저장소에 개인정보 금지: 실제 블루투스 주소(부분 포함), `C:\Users\<이름>` 경로, 로그/설정/캡처, `.venv`, `.claude`. `tools/package.py`가 빌드마다 검사해 실패시킴.
- 파괴적 명령은 UI 확인 필수. 개발 중 실기기에 파괴적 명령·이름 변경·LDAC/듀얼 변경·찾기 소리를 보내지 않는다(사용자 승인 범위 밖).
- 펌웨어 OTA 미구현.
- QCY 휴대폰 앱이 BLE로 연결 중이면 PC가 연결하지 못할 수 있음 → 배너 안내.
- git push / Release 전 사용자 확인 필수.

---

## 6. 현재 상태

- **단계: v1.0.0 완성 — GitHub 공개 저장소 + Release로 게시** (2026-09-29)
- GitHub: https://github.com/jykim5215/wireless-limitless (public). 마지막 업로드 버전 **v1.0.0** (Release 자산: `WirelessLimitless-1.0.0-win64.zip`, `.sha256`, `version.json`).
- 앱 내 업데이트: 구현 완료 — 시작 4초 후 자동 확인(설정에서 끌 수 있음) + 설정 › 앱 › 업데이트 확인. 설치 폴더에서만 자동 교체.
- 이 PC: `%LOCALAPPDATA%\Programs\WirelessLimitless`에 설치, 바탕화면·시작 메뉴 바로가기 생성됨.
- 검증:
  - 단위 테스트 58개 통과(`python -m pytest`).
  - 실기기 읽기 동기화 OK(약 8초 내 연결·동기화), 쓰기 검증 16/16 통과 후 원복(2회 실행, 빠른 연속 EQ 변경 포함).
  - 소스 실행·PyInstaller exe·설치본 모두 연결·표시 정상, 끊김 후 자동 재연결 확인.
  - 배포 zip 개인정보 검사 통과(기기 주소·사용자 경로·설정/로그 파일 없음).
- 확인된 이슈/관찰:
  - exe 테스트 중 EQ 프리셋을 연달아 바꾼 직후 연결이 1회 끊겼다가 6초 뒤 자동 재연결(원인 미확정: 이어버드를 케이스에 넣었을 가능성). 예방으로 EQ 전송을 0.6초 간격 + 최신 값만 전송하도록 변경했고, 재검증에서 재현되지 않음.
  - 미검증 쓰기: LDAC·듀얼 연결 전환, 이름 변경, 이어버드 찾기(0x05), 기본값 복원/공장 초기화 (사용자 승인 범위 밖 또는 파괴적).
- 다음 할 일(제안): 백로그 참고. 새 버전을 낼 때는 `version.json` 버전·changelog 수정 → `tools\build.ps1` → 커밋 → 사용자 확인 → push + `gh release create vX.Y.Z release\WirelessLimitless-X.Y.Z-win64.zip release\WirelessLimitless-X.Y.Z-win64.zip.sha256 release\version.json`.
