# Birkin

![Birkin — 신중한 지식 업무를 위한 접힌 문서 형태의 업무 공간](./docs/assets/birkin-readme-hero.png)

<p align="center"><strong>리서치와 Office 문서, 승인이 필요한 실행을 한곳에서 다루는 로컬 업무 공간.</strong></p>

<p align="center">
  <a href="./README.md">English</a> ·
  <a href="./docs/office-support.md">Office 지원 범위</a> ·
  <a href="./docs/DESIGN.md">아키텍처</a> ·
  <a href="./docs/config-reference.ko.md">설정</a>
</p>

Birkin은 대화, 근거를 남기는 리서치, 문서 작업, 승인을 하나의 로컬 업무 공간으로 연결합니다. Python이 실행과 정책을 맡고 Windows, macOS, 터미널, Web 화면은 같은 업무 상태를 보여 줍니다.

핵심은 ‘준비됨’과 ‘실행됨’을 구분하는 데 있습니다. 문서 변경은 저장 전에 검토할 수 있고, 중요한 작업은 승인 전까지 실행되지 않습니다. 완료 뒤에는 막연한 성공 메시지 대신 산출물과 검증 영수증을 남깁니다.

![리서치 결과, 문서 검토, 승인 요청을 함께 보여 주는 Birkin 업무 공간](./docs/assets/birkin-workspace-windows.png)

> 표지는 생성한 브랜드 일러스트입니다. 업무 공간 이미지는 대표 데이터를 사용해 만든 제품 방향 시안입니다. 두 이미지 모두 실제 Microsoft 365 세션이나 설치 패키지 인수 결과는 아닙니다.

## 할 수 있는 일

- **근거가 남는 리서치**: 공개 원문을 수집하고 출처로 확인한 사실, 근거에 기반한 추론, 아직 풀지 못한 질문을 나눠 결과와 인용을 함께 보관합니다.
- **Office 문서 검사와 변경 준비**: DOCX, XLSX, PPTX, PDF, HWPX를 읽고 추출·비교·검증하며, 새 문서를 만들거나 제한된 범위에서 원본을 보존한 채 수정합니다.
- **실행 전 검토**: 원본, 저장 위치, 정확한 변경 내용, 덮어쓰기 여부, 위험, 승인 상태를 보고 승인하거나 거부합니다.
- **추측하지 않는 복구**: 작업 기록과 영수증으로 완료·일부 완료·실패·결과 불확실을 구분합니다. 메일 발송 결과가 불확실하면 다시 보내기 전에 원격 상태부터 확인합니다.
- **로컬 우선 보관**: 세션, 기억, 승인, 감사 기록은 기본적으로 `BIRKIN_HOME` 아래에 둡니다. 설정한 모델 제공자는 요청 내용을 받을 수 있으며 Microsoft 365는 사용자가 연결한 경우에만 접속합니다.
- **필요한 화면 선택**: 터미널이나 로컬 Web 업무 공간에서 시작하고 Windows와 macOS Native 앱에서도 같은 Python 권한을 사용합니다.

## 기본 업무 흐름

1. 질문을 조사하거나 파일을 검사해 달라고 요청합니다.
2. 결과와 출처, 아직 확인하지 못한 내용을 검토합니다.
3. 문서 변경이나 외부 작업을 요청합니다.
4. 제안된 변경을 확인하고 승인하거나 거부합니다.
5. 생성된 산출물과 검증 영수증을 확인합니다.

기존 Office 파일을 바꾸려면 먼저 원본을 전용 `BIRKIN_HOME/office` 격리 경로로 가져와야 합니다. 원본은 그대로 두고 복사본에 변경하며 저장 위치도 허용된 범위 안으로 제한합니다. 승인 요청을 만들었다고 파일이 바뀌지는 않으며, 되돌리기도 별도 승인이 필요합니다.

```text
리서치 또는 파일 가져오기 → 결과와 근거 → 변경 제안
          → 사람의 승인 → 실행 + 산출물 + 영수증
```

## 빠른 시작

Python 3.10 이상이 필요합니다. 현재 저장소의 소스 버전은 Birkin `0.4.417`입니다. 이 표기는 같은 버전이 사용자 PC에 설치됐거나 서명된 공개 앱으로 배포됐다는 뜻이 아닙니다.

### Windows

```powershell
py -3 -m pip install .
birkin setup
birkin chat
```

현재 `main` 브랜치를 설치한 뒤 실제 버전을 확인할 수도 있습니다.

```powershell
irm https://raw.githubusercontent.com/ashmoonori-afk/birkin/main/scripts/install.ps1 | iex
birkin --version
birkin setup
birkin chat
```

WPF 앱은 개발용 화면입니다. .NET 8과 로컬 Birkin CLI가 필요합니다.

```powershell
dotnet run --project .\windows\BirkinNativeApp\src\Birkin.Native.App\Birkin.Native.App.csproj -c Release
```

이 저장소 상태에서는 서명된 Windows 고객용 패키지 설치를 확인하지 못했습니다. 자세한 내용은 [Birkin for Windows](./windows/BirkinNativeApp/README.md)를 참고하십시오.

### macOS와 Linux

```bash
python3 -m pip install .
birkin setup
birkin chat
```

```bash
curl -fsSL https://raw.githubusercontent.com/ashmoonori-afk/birkin/main/scripts/install.sh | bash
birkin --version
```

macOS SwiftUI 앱은 소스에서 빌드합니다. release 자격 증명 없이 만든 빌드는 개발용 artifact입니다. notarization, stapling, Gatekeeper 검사, 공개 배포는 별도 인수 단계입니다. [Native 앱 안내](./docs/native-app/README.md)를 참고하십시오.

### Web 업무 공간

Web 업무 공간은 같은 Python 실행 환경이 로컬에서 인증을 적용해 제공합니다.

```bash
birkin web
```

다른 클라이언트에서 비공개 bootstrap URL을 열 때는 `birkin web --no-browser`를 사용합니다. 기본으로 loopback 주소에만 열리고, 일회용 bootstrap capability를 `HttpOnly`, `SameSite=Strict` cookie로 교환합니다.

## Office와 리서치 기능 추가

```bash
python -m pip install ".[office]"          # DOCX, XLSX, PPTX, HWPX
python -m pip install ".[office-advanced]" # PDF 추출과 제한된 페이지 렌더
python -m pip install ".[research]"        # 리서치 스키마와 canonical record
```

Office 기능은 범위가 정해진 문서 작업이며 데스크톱 Office 프로그램을 마음대로 자동화하는 기능이 아닙니다.

| 포맷 | 현재 공개 경로 | 경계 |
| --- | --- | --- |
| DOCX | 검사, 추출, 생성, 제한된 수정, 구조화 미리보기 | 레이아웃과 변경 내용 추적 검증 없음 |
| XLSX | 검사, 추출, 생성, 숫자 셀 수정, 구조화 미리보기 | 수식은 보존하지만 재계산하지 않음 |
| PPTX | 검사, 추출, 생성, 자리표시자 수정, 구조화 미리보기 | master, animation, overflow, 레이아웃 검증 없음 |
| PDF | 검사·생성, 선택적 추출과 한 페이지 이미지 | 기존 PDF는 읽기 전용이며 양식·서명·OCR·redaction 미지원 |
| HWPX | 검사, 추출, 생성, template field, 제한된 field 수정 | 구형 HWP와 한컴 프로그램 자동화 미지원 |

정확한 도구 목록, package provenance, 제한, 거부 조건은 [Office 지원 계약](./docs/office-support.md)에 있습니다.

## 모델 제공자와 자주 쓰는 명령

`birkin setup`에서 모델 제공자와 모델을 설정합니다. 기본 설정은 로컬 `codex-cli` 모델 제공자를 사용하며 API 제공자나 호환 endpoint는 각 서비스의 자격 증명이 필요합니다.

```bash
birkin --version
birkin --help
birkin chat --dry-run "이 요청을 요약해줘" # prompt packet만 만들고 전송하지 않음
birkin review                              # 대기 중인 승인 검토
```

전체 설정표는 [설정 참조](./docs/config-reference.ko.md)에 있습니다. 사용자용 한국어와 protocol·진단용 영어의 기준은 [언어 정책](./docs/language-policy.md)을 따릅니다.

## 신뢰 경계

- 문서 본문, URL, 수식, macro, metadata, embedded object는 신뢰하지 않는 입력으로 다룹니다.
- 읽기와 검사는 쓰기 권한을 만들지 않습니다. Office 변경은 `office_job_request`, 되돌리기는 `office_rollback_request`를 통해서만 요청합니다.
- 승인은 원본 hash, 작업 내용, 저장 위치, 덮어쓰기 선택, 제안자를 정확히 묶습니다. 입력이 바뀌면 실행을 중단합니다.
- Browser와 Computer Use는 선택 기능이며 설정 전에는 꺼져 있습니다. 허용 목록, 작업 횟수 제한, 승인 정책의 적용을 받습니다.
- 모델 제공자 응답, HTTP 접수, 로컬 영수증, 확인된 원격 상태는 서로 다른 증거입니다. 외부 결과를 관측할 수 없으면 `unknown`이나 `needs_review` 상태를 유지합니다.

## 확인된 범위와 현재 한계

저장소 테스트와 제한된 로컬 실행으로 Python 권한, 승인·복구 계약, Web 동작, Native protocol projection을 검증했습니다. 대표 DOCX 한 건은 자연어 검사부터 Native 승인, 파일 저장, 영수증 확인까지 통과했고 승인 전에는 결과 파일이 생기지 않았습니다.

이 결과만으로 공개 제품 전체가 인수됐다고 볼 수는 없습니다.

- 소스 버전만으로 실제 설치 버전이나 공개 배포 버전을 알 수 없습니다.
- 최신 리서치 실행에는 미확정 주장이 남았고 답변 전체 인수를 통과하지 못했습니다.
- mock/offline 렌더와 keyboard 검사는 통과했지만 실제 설치본 여정, macOS CI 후속 확인, 사람의 화면 읽기 프로그램 검토가 남아 있습니다.
- Microsoft 365 실제 계정 검증은 마지막 단계로 두었으며 아직 완료하지 않았습니다.
- Windows 서명 package와 macOS notarized public 배포를 확인하지 못했습니다.

근거와 남은 조건은 [Office 에이전트 리뷰](./docs/office-agent-review.md), [UI 재설계 기준](./docs/ui-redesign-spec.md), [Windows 첫 리포트 여정](./docs/windows-first-report-journey.md)에 기록돼 있습니다.

## 문서 안내

| 찾는 내용 | 문서 |
| --- | --- |
| 정확한 Office 기능 | [Office Work OS v2](./docs/office-support.md) |
| UI 동작과 접근성 기준 | [UI 재설계 기준](./docs/ui-redesign-spec.md) |
| 현재 구현과 남은 조건 | [Office 에이전트 리뷰](./docs/office-agent-review.md) |
| 전체 설정 스키마 | [설정 참조](./docs/config-reference.ko.md) |
| 실행 환경 아키텍처 | [설계 문서](./docs/DESIGN.md) |
| 기억 시스템 | [Mnemosyne 설계](./docs/mnemosyne-design.md) |
| 멀티 에이전트 업무 흐름 | [Moirai 설계](./docs/moirai-design.md) |
| Native protocol과 보안 | [Native 앱 문서](./docs/native-app/README.md) |
| 현재 개발 상태 | [상태 문서](./docs/STATUS.md) |
| VS Code client | [Extension](./vscode-extension) |

## 개발

```bash
python -m pip install -e ".[dev]"
pytest
```

Native와 Browser test에는 플랫폼별 준비가 더 필요합니다. 일부 로컬 test 통과를 여러 플랫폼의 전체 인수로 해석하지 말고 위의 문서를 따라 확인하십시오.

Birkin은 [MIT License](./LICENSE)로 배포합니다. 외부 구성 요소의 저작권과 조건은 [NOTICE](./NOTICE), `LICENSES/`, Office [third-party notice](./birkin/office/adapters/THIRD_PARTY_NOTICES.md)에 기록돼 있습니다.
