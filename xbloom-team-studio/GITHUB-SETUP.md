# GitHub 소스 실행 안내

이 폴더는 xBloom Team Studio 배포 소스의 사본입니다. 현재 사이트는 https://xbloom-team-studio-jh.plucky-clock-3869.chatgpt.site/ 입니다.

## 로컬 실행

Node.js 22.13 이상(검증 환경: 24.14.1)이 필요합니다. 터미널에서 이 폴더로 이동한 뒤 실행하세요.

```sh
npm ci
node -e "require('fs').writeFileSync('.dev.vars', 'XBLOOM_ENCRYPTION_KEY=' + require('crypto').randomBytes(32).toString('hex') + '\n')"
npm run build
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0000_fancy_reptil.sql
node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0001_blue_patch.sql
npm run dev
```

암호화 키 생성은 첫 설정 때 한 번만 하세요. 기존 .dev.vars를 덮어쓰면 저장한 xBloom 연결 정보를 복호화할 수 없습니다.

표시되는 로컬 주소(기본 http://127.0.0.1:5173/)에서 웹에 로그인하면 개발용 계정으로 접속합니다. 공유 공간을 시작한 뒤 연결 설정에 xBloom 계정을 입력하세요. 실제 계정은 소스에 포함되어 있지 않습니다. 로컬 데이터와 배포 사이트의 데이터는 별개입니다.

## 검사

```sh
node node_modules/typescript/bin/tsc --noEmit --incremental false
node --experimental-transform-types --test tests/protocol.test.ts tests/editor-parity.test.ts tests/bluetooth.test.ts
npm run build
```

## 배포 및 Bluetooth

서버 실행에는 Cloudflare D1, XBLOOM_ENCRYPTION_KEY secret, Sites의 웹 인증 구성이 필요합니다. GitHub Pages 같은 정적 호스팅만으로는 계정/API 기능이 실행되지 않습니다. .openai/hosting.json의 project_id는 기존 배포 사이트를 가리키므로, 새 사이트를 만들 때는 새 Site ID와 환경을 구성해야 합니다.

기기 근처의 지원 브라우저에서 Bluetooth 추출을 사용합니다. Studio 커피 레시피만 지원하며 실제 사용자 기기에서의 동작 검증은 필요합니다. 자세한 기능과 제한은 README.md 및 EDITOR-PARITY.md에 있습니다.

node_modules, 빌드 결과, 로컬 DB, .dev.vars, 계정 비밀번호, 암호화 키, APK는 업로드하지 않습니다.
