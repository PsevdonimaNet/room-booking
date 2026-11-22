// Нагрузочный (стресс) тест: рост нагрузки от 50 до 200 запросов в секунду.
// Запуск: docker compose -f docker-compose.yml -f docker-compose.monitoring.yml --profile load run --rm k6
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE = __ENV.BASE_URL || 'http://web:8000';
const USERS = parseInt(__ENV.LOAD_USERS || '20');
const PASSWORD = __ENV.LOAD_PASSWORD || 'demo12345';

// Ответы 400 и 409 (правила и конфликты бронирования) - ожидаемое поведение, не сбой.
http.setResponseCallback(http.expectedStatuses({ min: 200, max: 299 }, 400, 409));

// Без RATE - ступенчатый рост 50 -> 200 запросов/с. С RATE=100 - постоянная нагрузка (RATE запросов/с).
const RATE = parseInt(__ENV.RATE || '0');
const DURATION = __ENV.DURATION || '1m';

const rampScenario = {
  executor: 'ramping-arrival-rate',
  startRate: 10,
  timeUnit: '1s',
  preAllocatedVUs: 100,
  maxVUs: 500,
  stages: [
    { target: 50, duration: '30s' },
    { target: 100, duration: '1m' },
    { target: 200, duration: '1m' },
    { target: 200, duration: '1m' },
    { target: 0, duration: '20s' },
  ],
};

const constantScenario = {
  executor: 'constant-arrival-rate',
  rate: RATE,
  timeUnit: '1s',
  duration: DURATION,
  preAllocatedVUs: 100,
  maxVUs: 500,
};

export const options = {
  noCookiesReset: true, // сохранять сессию между итерациями виртуального пользователя
  scenarios: { load: RATE > 0 ? constantScenario : rampScenario },
  thresholds: {
    'http_req_duration{kind:api}': ['p(95)<200'],
    'http_req_failed{kind:api}': ['rate<0.001'],
    checks: ['rate>0.99'],
  },
};

// Вход выполняется один раз на пользователя в setup(), а не в каждом виртуальном пользователе:
// хэширование пароля нагружает процессор, и массовый вход искажает измерения API.
function login(username) {
  const jar = new http.CookieJar();
  http.get(`${BASE}/accounts/login/`, { jar, tags: { kind: 'login' } });
  const csrf = jar.cookiesForURL(`${BASE}/`).csrftoken[0];
  const res = http.post(
    `${BASE}/accounts/login/`,
    { username, password: PASSWORD, csrfmiddlewaretoken: csrf },
    { jar, tags: { kind: 'login' }, headers: { Referer: `${BASE}/accounts/login/` } },
  );
  const ok = check(res, { 'login ok': (r) => r.status === 200 && !r.url.includes('/login/') });
  if (!ok) return null;
  const cookies = jar.cookiesForURL(`${BASE}/`);
  return { sid: cookies.sessionid[0], csrf: cookies.csrftoken[0] };
}

export function setup() {
  const sessions = [];
  for (let i = 1; i <= USERS; i++) {
    const session = login(`load${i}`);
    if (!session) {
      throw new Error(`Не удалось войти как load${i}. Создайте пользователей: python manage.py seed_demo --load-users ${USERS}`);
    }
    sessions.push(session);
  }
  const jar = new http.CookieJar();
  jar.set(BASE, 'sessionid', sessions[0].sid);
  const rooms = http.get(`${BASE}/api/rooms/`, { jar, tags: { kind: 'setup' } }).json();
  return { roomIds: rooms.map((r) => r.id), sessions };
}

let ready = false;
const pad = (n) => String(n).padStart(2, '0');

function futureSlot() {
  const days = 1 + Math.floor(Math.random() * 14);
  const length = 1 + Math.floor(Math.random() * 2);
  const hour = 8 + Math.floor(Math.random() * (12 - length + 1));
  const d = new Date(Date.now() + days * 86400000);
  const date = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
  return { date, start: `${date}T${pad(hour)}:00:00+03:00`, end: `${date}T${pad(hour + length)}:00:00+03:00` };
}

export default function (data) {
  if (!ready) {
    // Каждый виртуальный пользователь берёт готовую сессию одного из load-пользователей.
    const session = data.sessions[__VU % data.sessions.length];
    const jar = http.cookieJar();
    jar.set(BASE, 'sessionid', session.sid);
    jar.set(BASE, 'csrftoken', session.csrf);
    ready = true;
  }

  const roomId = data.roomIds[Math.floor(Math.random() * data.roomIds.length)];
  const dice = Math.random();

  if (dice < 0.65) {
    const res = http.get(`${BASE}/api/rooms/`, { tags: { kind: 'api', name: 'rooms' } });
    check(res, { 'rooms 200': (r) => r.status === 200 });
  } else if (dice < 0.8) {
    const slot = futureSlot();
    const res = http.get(`${BASE}/api/rooms/${roomId}/availability/?date=${slot.date}`, {
      tags: { kind: 'api', name: 'availability' },
    });
    check(res, { 'availability 200': (r) => r.status === 200 });
  } else if (dice < 0.92) {
    const res = http.get(`${BASE}/api/bookings/`, { tags: { kind: 'api', name: 'history' } });
    check(res, { 'history 200': (r) => r.status === 200 });
  } else {
    const slot = futureSlot();
    const csrf = http.cookieJar().cookiesForURL(`${BASE}/`).csrftoken[0];
    const res = http.post(
      `${BASE}/api/bookings/`,
      JSON.stringify({ room: roomId, start: slot.start, end: slot.end }),
      {
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf, Referer: `${BASE}/` },
        tags: { kind: 'api', name: 'create_booking' },
      },
    );
    check(res, { 'booking 201/400/409': (r) => [201, 400, 409].includes(r.status) });
  }
}
