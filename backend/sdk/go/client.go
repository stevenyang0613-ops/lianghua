// 西部量化可转债策略 V3.0 Go SDK
// 文件: client.go

package sgstrategy

import (
	"bytes"
	"crypto/hmac"
	"crypto/md5"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"
)

// ClientConfig 客户端配置
type ClientConfig struct {
	APIKey     string
	APISecret  string
	BaseURL    string
	Timeout    int
	MaxRetries int
}

// Client 西部策略客户端
type Client struct {
	config     ClientConfig
	httpClient *http.Client
}

// APIResponse API响应
type APIResponse struct {
	Success    bool        `json:"success"`
	StatusCode int         `json:"status_code"`
	Data       interface{} `json:"data"`
	Message    string      `json:"message"`
	RequestID  string      `json:"request_id"`
}

// NewClient 创建新客户端
func NewClient(apiKey, apiSecret, baseURL string) *Client {
	if baseURL == "" {
		baseURL = "https://api.sg-strategy.com"
	}

	return &Client{
		config: ClientConfig{
			APIKey:     apiKey,
			APISecret:  apiSecret,
			BaseURL:    baseURL,
			Timeout:    30,
			MaxRetries: 3,
		},
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// generateSignature 生成签名
func (c *Client) generateSignature(method, path string, params url.Values, body string) map[string]string {
	timestamp := strconv.FormatInt(time.Now().Unix(), 10)
	nonce := md5Hash(timestamp + c.config.APIKey)[:16]

	// 构建查询字符串
	queryString := ""
	if params != nil {
		keys := make([]string, 0, len(params))
		for k := range params {
			keys = append(keys, k)
		}
		sort.Strings(keys)

		var sb strings.Builder
		for i, k := range keys {
			if i > 0 {
				sb.WriteString("&")
			}
			sb.WriteString(k + "=" + params.Get(k))
		}
		queryString = sb.String()
	}

	// 签名字符串
	signStr := fmt.Sprintf("%s\n%s\n%s\n%s\n%s",
		strings.ToUpper(method),
		path,
		queryString,
		body,
		timestamp,
	)

	signature := hmacSha256(c.config.APISecret, signStr)

	return map[string]string{
		"X-API-Key":    c.config.APIKey,
		"X-Timestamp":  timestamp,
		"X-Nonce":      nonce,
		"X-Signature":  signature,
		"Content-Type": "application/json",
	}
}

// request 发送请求
func (c *Client) request(method, path string, params url.Values, body interface{}) (*APIResponse, error) {
	urlStr := c.config.BaseURL + path

	var bodyReader io.Reader
	var bodyStr string
	if body != nil {
		bodyBytes, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		bodyStr = string(bodyBytes)
		bodyReader = bytes.NewReader(bodyBytes)
	}

	// 添加查询参数
	if params != nil {
		urlStr = urlStr + "?" + params.Encode()
	}

	req, err := http.NewRequest(method, urlStr, bodyReader)
	if err != nil {
		return nil, err
	}

	// 设置签名头
	headers := c.generateSignature(method, path, params, bodyStr)
	for k, v := range headers {
		req.Header.Set(k, v)
	}

	// 发送请求
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	// 解析响应
	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}

	var result map[string]interface{}
	if err := json.Unmarshal(respBody, &result); err != nil {
		return nil, err
	}

	return &APIResponse{
		Success:    resp.StatusCode == 200,
		StatusCode: resp.StatusCode,
		Data:       result["data"],
		Message:    getString(result, "message"),
		RequestID:  resp.Header.Get("X-Request-ID"),
	}, nil
}

// ============ API方法 ============

// ScoreBond 单个转债打分
func (c *Client) ScoreBond(code string, date string) (*APIResponse, error) {
	params := url.Values{}
	if date != "" {
		params.Set("date", date)
	}
	return c.request("GET", "/api/v3/scoring/score/"+code, params, nil)
}

// ScoreBonds 批量打分
func (c *Client) ScoreBonds(codes []string, date string) (*APIResponse, error) {
	body := map[string]interface{}{
		"codes": codes,
	}
	if date != "" {
		body["date"] = date
	}
	return c.request("POST", "/api/v3/scoring/score", nil, body)
}

// GetWhitelist 获取白名单
func (c *Client) GetWhitelist(date string, topN int) (*APIResponse, error) {
	params := url.Values{}
	params.Set("top_n", strconv.Itoa(topN))
	if date != "" {
		params.Set("date", date)
	}
	return c.request("GET", "/api/v3/scoring/whitelist", params, nil)
}

// GenerateSignals 生成交易信号
func (c *Client) GenerateSignals(portfolioID string, mode string, constraints map[string]interface{}) (*APIResponse, error) {
	body := map[string]interface{}{}
	if portfolioID != "" {
		body["portfolio_id"] = portfolioID
	}
	if mode != "" {
		body["mode"] = mode
	}
	if constraints != nil {
		body["constraints"] = constraints
	}
	return c.request("POST", "/api/v3/signals/generate", nil, body)
}

// GetPositions 获取持仓
func (c *Client) GetPositions(portfolioID string) (*APIResponse, error) {
	params := url.Values{}
	if portfolioID != "" {
		params.Set("portfolio_id", portfolioID)
	}
	return c.request("GET", "/api/v3/positions", params, nil)
}

// GetRiskMetrics 获取风险指标
func (c *Client) GetRiskMetrics() (*APIResponse, error) {
	return c.request("GET", "/api/v3/risk/metrics", nil, nil)
}

// CalculateVar 计算VaR
func (c *Client) CalculateVar(confidence float64, method string, horizon int) (*APIResponse, error) {
	body := map[string]interface{}{
		"confidence": confidence,
		"method":     method,
		"horizon":    horizon,
	}
	return c.request("POST", "/api/v3/risk/var", nil, body)
}

// RunBacktest 运行回测
func (c *Client) RunBacktest(startDate, endDate string, initialCapital float64, strategyParams map[string]interface{}) (*APIResponse, error) {
	body := map[string]interface{}{
		"start_date":      startDate,
		"end_date":        endDate,
		"initial_capital": initialCapital,
	}
	if strategyParams != nil {
		body["strategy_params"] = strategyParams
	}
	return c.request("POST", "/api/v3/backtest/run", nil, body)
}

// HealthCheck 健康检查
func (c *Client) HealthCheck() (*APIResponse, error) {
	return c.request("GET", "/api/v3/system/health", nil, nil)
}

// Close 关闭客户端
func (c *Client) Close() {
	if c.httpClient != nil {
		c.httpClient.CloseIdleConnections()
	}
}

// ============ 工具函数 ============

func md5Hash(s string) string {
	h := md5.New()
	h.Write([]byte(s))
	return hex.EncodeToString(h.Sum(nil))
}

func hmacSha256(key, data string) string {
	h := hmac.New(sha256.New, []byte(key))
	h.Write([]byte(data))
	return hex.EncodeToString(h.Sum(nil))
}

func getString(m map[string]interface{}, key string) string {
	if v, ok := m[key]; ok {
		if s, ok := v.(string); ok {
			return s
		}
	}
	return ""
}
