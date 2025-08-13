Following is the link to the recording-https://www.loom.com/share/64074379f90d4d0f9a0d0995765a11d7?sid=dfbe4d94-9c20-4244-85f1-98cd7cc36226


Instructions:
# Nanda Agent SDK (Go)

Minimal base SDK for building Nanda-style agents in Go. It exposes simple HTTP endpoints you can use to build agents and test message flows.

## Requirements
- Go 1.20+ (tested on macOS)
- curl (for tests)



```bash
# clone and enter
git clone https://github.com/<your-username>/nanda-agent-sdk-go.git
cd nanda-agent-sdk-go

# run on port 5050
PORT=5050 go run ./...

Sample Output:
NANDA-Go agent listening on :5050
Endpoints: GET /api/health | POST /api/send | GET /api/render | GET /api/agents/list

