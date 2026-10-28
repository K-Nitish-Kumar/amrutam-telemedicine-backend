// Read-only smoke load. Run: k6 run -e API_URL=http://localhost:8000 infra/k6.js
import http from 'k6/http';
import { check, sleep } from 'k6';
export const options = {
  scenarios: { reads: { executor: 'ramping-vus', startVUs: 5,
    stages: [{duration: '30s', target: 25}, {duration: '1m', target: 100},
             {duration: '30s', target: 0}], gracefulRampDown: '10s' } },
  thresholds: { 'http_req_duration{endpoint:doctors}': ['p(95)<200'], 'http_req_failed': ['rate<0.01'] }
};
export default function () {
  const res = http.get(`${__ENV.API_URL || 'http://127.0.0.1:8000'}/doctors?limit=20`,
                       {tags: {endpoint: 'doctors'}});
  check(res, {'HTTP 200': r => r.status === 200});
  sleep(1);
}
