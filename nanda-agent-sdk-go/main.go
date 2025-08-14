package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

type Health struct {
	Status          string `json:"status"`
	Name            string `json:"name"`
	UptimeSec       int64  `json:"uptime_sec"`
	Messages        int64  `json:"messages"`
	RateLimitPerMin int    `json:"rate_limit_per_min"`
	Version         string `json:"version"`
}

type SendRequest struct {
	Message string `json:"message"`
}

type SendResponse struct {
	Input  string `json:"input"`
	Output string `json:"output"`
}

type RenderResponse struct {
	Latest string `json:"latest"`
}

type AgentInfo struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

var (
	start       = time.Now()
	msgCount    int64
	lastMsg     string
	mu          sync.Mutex
	memFile     = "memory.json"
	ratePerMin  = 60
	bucketMin   int64
	bucketCount int
)

type memory struct {
	Notes []struct {
		Text string `json:"text"`
		TS   string `json:"ts"`
	} `json:"notes"`
	Metrics struct {
		Messages int64   `json:"messages"`
		StartTS  float64 `json:"start_ts"`
	} `json:"metrics"`
}

func loadMem() memory {
	var m memory
	f, err := os.ReadFile(memFile)
	if err != nil {
		m.Metrics.StartTS = float64(time.Now().Unix())
		return m
	}
	_ = json.Unmarshal(f, &m)
	return m
}

func saveMem(m memory) {
	b, _ := json.MarshalIndent(m, "", "  ")
	_ = os.WriteFile(memFile, b, 0644)
}

func improve(s string) string {
	out := strings.ReplaceAll(s, "hello", "greetings")
	out = strings.ReplaceAll(out, "Hello", "Greetings")
	out = strings.ReplaceAll(out, "goodbye", "farewell")
	return "[nanda-go] " + out
}

func rateOK() bool {
	nowBucket := time.Now().Unix() / 60
	if nowBucket != bucketMin {
		bucketMin = nowBucket
		bucketCount = 0
	}
	if bucketCount >= ratePerMin {
		return false
	}
	bucketCount++
	return true
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	mu.Lock()
	defer mu.Unlock()
	h := Health{
		Status:          "ok",
		Name:            "ts-alt: nanda-go-agent",
		UptimeSec:       int64(time.Since(start).Seconds()),
		Messages:        msgCount,
		RateLimitPerMin: ratePerMin,
		Version:         "0.1.0",
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(h)
}

func sendHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	mu.Lock()
	defer mu.Unlock()

	if !rateOK() {
		http.Error(w, "rate limit exceeded", http.StatusTooManyRequests)
		return
	}

	var req SendRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "bad request", http.StatusBadRequest)
		return
	}

	out := improve(req.Message)
	lastMsg = out
	msgCount++

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(SendResponse{
		Input:  req.Message,
		Output: out,
	})

	m := loadMem()
	m.Metrics.Messages = msgCount
	if m.Metrics.StartTS == 0 {
		m.Metrics.StartTS = float64(start.Unix())
	}
	saveMem(m)
}

func renderHandler(w http.ResponseWriter, r *http.Request) {
	mu.Lock()
	defer mu.Unlock()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(RenderResponse{Latest: lastMsg})
}

func agentsListHandler(w http.ResponseWriter, r *http.Request) {
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode([]AgentInfo{
        {ID: "harshit-go-agent", Name: "nanda-go-agent"},
    })
}


func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/health", healthHandler)
	mux.HandleFunc("/api/send", sendHandler)
	mux.HandleFunc("/api/render", renderHandler)
	mux.HandleFunc("/api/agents/list", agentsListHandler)

	port := "5000"
	if p := os.Getenv("PORT"); p != "" {
		port = p
	}
	addr := ":" + port

	certFile := os.Getenv("CERT_FILE")
	keyFile := os.Getenv("KEY_FILE")

	if certFile != "" && keyFile != "" {
		log.Printf("NANDA-Go agent listening (HTTPS) on %s", addr)
		log.Printf("Endpoints: GET /api/health | POST /api/send | GET /api/render | GET /api/agents/list")
		if err := http.ListenAndServeTLS(addr, certFile, keyFile, mux); err != nil {
			log.Fatal(err)
		}
	} else {
		log.Printf("NANDA-Go agent listening (HTTP) on %s", addr)
		log.Printf("Endpoints: GET /api/health | POST /api/send | GET /api/render | GET /api/agents/list")
		if err := http.ListenAndServe(addr, mux); err != nil {
			log.Fatal(err)
		}
	}
}
