/** @type {import('next').NextConfig} */
const nextConfig = {
  agentRules: false,
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://backend:8000/api/:path*",
      },
    ];
  },
};

export default nextConfig;
