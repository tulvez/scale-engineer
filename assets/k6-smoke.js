// scale-engineer: ramping load test for calibration.
// Usage: k6 run -e BASE_URL=https://staging.example.com -e PATHS=/,/api/feed assets/k6-smoke.js
// Run against staging only. Free and capped plans spend their quota on this test.
import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE = __ENV.BASE_URL;
if (!BASE) throw new Error('Set BASE_URL, e.g. -e BASE_URL=https://staging.example.com');
const PATHS = (__ENV.PATHS || '/').split(',').map((p) => p.trim()).filter(Boolean);
const MAX_VUS = Number(__ENV.MAX_VUS || 100);

export const options = {
  stages: [
    { duration: '30s', target: Math.ceil(MAX_VUS * 0.1) },
    { duration: '1m', target: Math.ceil(MAX_VUS * 0.5) },
    { duration: '1m', target: MAX_VUS },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_failed: [{ threshold: 'rate<0.01', abortOnFail: true }],
    http_req_duration: ['p(95)<2000'],
  },
  summaryTrendStats: ['avg', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  const path = PATHS[Math.floor(Math.random() * PATHS.length)];
  const res = http.get(`${BASE}${path}`, { tags: { path } });
  check(res, { 'status < 400': (r) => r.status < 400 });
  sleep(1 + Math.random() * 2); // think time between user actions
}
