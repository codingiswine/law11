# Law11 React Frontend

Vite + React 19 + Tailwind CSS 4 기반의 스트리밍 챗 UI입니다.
FastAPI 백엔드가 보내는 Server-Sent Events(SSE)를 파싱해 실시간 타자 효과로 답변을 표시하고,
인용된 조문은 사이드패널에서 원문을 바로 확인할 수 있습니다.

전체 시스템 설명은 [저장소 루트 README](../README.md)를 참고하세요.

---

## 🚀 Quick start

```bash
cd law11_frontend
npm install
npm run dev
```

브라우저에서 <http://localhost:5173> 접속. 백엔드가 함께 떠 있어야 합니다 (`../law11_backend/README.md`).

### Scripts
| 명령어 | 설명 |
| ---- | ---- |
| `npm run dev` | Vite 개발 서버 (HMR) |
| `npm run build` | `tsc -b` 타입체크 + 프로덕션 번들 |
| `npm run preview` | 빌드 결과 미리보기 |
| `npm run lint` | ESLint 점검 |

Node 20+ 권장 (CI는 Node 20).

---

## 🔌 Backend integration

API 주소는 `VITE_API_URL` 환경변수로 지정하며, 미설정 시 `http://localhost:8000` 을 씁니다.
**Vite 빌드 타임에 인라인되는 값**이라, 배포 시에는 빌드 전에 설정해야 합니다.

```bash
# .env 또는 .env.local
VITE_API_URL=http://localhost:8000
```

`src/services/api.ts` 가 감싸는 백엔드 엔드포인트:

| 함수 | 호출 |
| ---- | ---- |
| `submitFeedback()` | `POST /api/feedback` |
| `getLawContent()` | `GET /api/law?name=&article=` (둘 다 필수, 생략 시 422) |
| `getHistory()` | `GET /api/history` → session_id 별 그룹핑 후 최근 활동순 정렬 |
| `getSession()` | `GET /api/session/{id}` |
| `deleteSession()` | `DELETE /api/session/{id}` |

SSE 스트리밍(`POST /api/ask`)만 `ChatWindow.tsx` 가 직접 `fetch` + `ReadableStream` 으로 처리합니다.

```tsx
const response = await fetch(`${API_BASE_URL}/api/ask`, { method: "POST", ... });
const reader = response.body?.getReader();
const decoder = new TextDecoder("utf-8");
// JSON 라인별 파싱 → event 타입에 따라 answer / status / sources 갱신
```

| event | UI 렌더링 |
| ---- | ---- |
| `text` | 답변 버블 (Markdown 렌더링) |
| `status` | 회색 작은 상태 라벨 |
| `source` | 참고 법령 배지 → 클릭 시 `LawSidePanel` 오픈 |
| `error` | 빨간 상태 라벨 (비치명적 경고 포함) |

---

## 🧱 Project layout

```
src/
├── main.tsx                # React 엔트리포인트
├── App.tsx                 # 루트 컴포넌트 (세션 상태, 레이아웃)
├── components/
│   ├── ChatWindow.tsx      # SSE 파싱 + 스트리밍 렌더링 + 참고 법령 배지
│   ├── ChatMessage.tsx     # User/Assistant 말풍선 (Markdown + 피드백 버튼)
│   ├── LawSidePanel.tsx    # 인용 조문 원문 패널 (DB 미등록 시 법령정보원 링크)
│   ├── SearchBar.tsx       # 질문 입력 + 한글 IME 대응
│   └── Sidebar.tsx         # 세션 목록 / 삭제
├── services/api.ts         # 백엔드 REST 호출 래퍼
├── types/index.ts          # LawSource, Message, LawArticle, SessionSummary 등
├── index.css / App.css     # Tailwind 엔트리 + 커스텀 스타일
└── vite-env.d.ts           # import.meta.env 타입 (VITE_API_URL)
```

---

## 🎨 UI notes

- `react-markdown` + `remark-gfm` + `@tailwindcss/typography` 로 목록/표/링크 렌더링
- 스트리밍 중 `useRef` + `scrollIntoView` 로 자동 스크롤
- `SearchBar` 가 `onCompositionStart/End` 를 처리해 한글 입력 중 `Enter` 오전송 방지
- Tailwind 유틸 클래스로 모바일/데스크탑 대응

---

## 🧪 Quality

타입체크·린트만 사용하고 별도 테스트 러너는 두지 않았습니다.

```bash
npm run lint    # ESLint (typescript-eslint + react-hooks)
npm run build   # tsc -b 타입체크 포함
```

CI(`../.github/workflows/ci.yml`)가 push/PR마다 `npm ci` → `npm run build` 를 실행합니다.
`playwright` 가 devDependency 에 있지만 현재 E2E 테스트 스위트는 없습니다 (수동 확인용).

---

## 🐛 Troubleshooting

| 증상 | 확인 사항 |
| ---- | -------- |
| CORS 오류 | 백엔드 `.env` 의 `CORS_ORIGINS` 에 프론트 URL 추가 |
| API 연결 실패 | 백엔드 기동 여부, `VITE_API_URL` 값 (빌드 타임 인라인이라 **재빌드** 필요) |
| 스트림 중지 | 브라우저 콘솔의 파싱 에러와 백엔드 `logs/<날짜>/error.log` 대조 |
| 사이드패널이 비어 있음 | 해당 조문이 DB 미등록 — 법령정보원 링크로 폴백되는 것이 정상 |
| Tailwind 미적용 | `npm install` 후 재기동, `postcss.config.js` 존재 확인 |

---

## 📝 라이선스

MIT — 저장소 루트 [LICENSE](../LICENSE) 참고.
