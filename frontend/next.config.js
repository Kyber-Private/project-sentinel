/** @type {import('next').NextConfig} */
const backend = process.env.SENTINEL_BACKEND_URL || "http://127.0.0.1:8000";
module.exports = {
  reactStrictMode: true,
  async rewrites() {
    // The browser only talks to Next.js; API calls are proxied to FastAPI.
    // The OpenAI key stays on the backend and is never sent to the browser.
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};
