// 松岗量化可转债策略 V3.0 Java SDK
// 文件: SgStrategyClient.java

package com.sgstrategy.sdk;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;
import org.apache.http.client.methods.*;
import org.apache.http.entity.StringEntity;
import org.apache.http.impl.client.CloseableHttpClient;
import org.apache.http.impl.client.HttpClients;
import org.apache.http.util.EntityUtils;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

/**
 * 松岗策略Java客户端
 */
public class SgStrategyClient {

    private final String apiKey;
    private final String apiSecret;
    private final String baseUrl;
    private final int timeout;
    private final ObjectMapper objectMapper;
    private final CloseableHttpClient httpClient;

    /**
     * 构造函数
     */
    public SgStrategyClient(String apiKey, String apiSecret, String baseUrl, int timeout) {
        this.apiKey = apiKey;
        this.apiSecret = apiSecret;
        this.baseUrl = baseUrl != null ? baseUrl : "https://api.sg-strategy.com";
        this.timeout = timeout > 0 ? timeout : 30000;
        this.objectMapper = new ObjectMapper();
        this.httpClient = HttpClients.custom()
                .setConnectionRequestTimeout(this.timeout)
                .setConnectTimeout(this.timeout)
                .setSocketTimeout(this.timeout)
                .build();
    }

    public SgStrategyClient(String apiKey, String apiSecret) {
        this(apiKey, apiSecret, null, 0);
    }

    /**
     * 生成签名
     */
    private Map<String, String> generateSignature(String method, String path,
                                                    Map<String, String> params, String body) {
        String timestamp = String.valueOf(System.currentTimeMillis() / 1000);
        String nonce = md5(timestamp + apiKey).substring(0, 16);

        // 构建查询字符串
        String queryString = "";
        if (params != null && !params.isEmpty()) {
            List<String> sortedKeys = new ArrayList<>(params.keySet());
            Collections.sort(sortedKeys);
            StringBuilder sb = new StringBuilder();
            for (String key : sortedKeys) {
                if (sb.length() > 0) sb.append("&");
                sb.append(key).append("=").append(params.get(key));
            }
            queryString = sb.toString();
        }

        // 签名字符串
        String signStr = method.toUpperCase() + "\n" + path + "\n" +
                        queryString + "\n" + (body != null ? body : "") + "\n" + timestamp;

        String signature = hmacSha256(apiSecret, signStr);

        Map<String, String> headers = new HashMap<>();
        headers.put("X-API-Key", apiKey);
        headers.put("X-Timestamp", timestamp);
        headers.put("X-Nonce", nonce);
        headers.put("X-Signature", signature);
        headers.put("Content-Type", "application/json");

        return headers;
    }

    /**
     * 发送请求
     */
    private ApiResponse request(String method, String path,
                                 Map<String, String> params, Object body) throws Exception {
        String url = baseUrl + path;
        String jsonBody = body != null ? objectMapper.writeValueAsString(body) : "";

        Map<String, String> headers = generateSignature(method, path, params, jsonBody);

        HttpRequestBase httpRequest;
        if ("GET".equals(method)) {
            HttpGet get = new HttpGet(url);
            httpRequest = get;
        } else if ("POST".equals(method)) {
            HttpPost post = new HttpPost(url);
            if (!jsonBody.isEmpty()) {
                post.setEntity(new StringEntity(jsonBody, StandardCharsets.UTF_8));
            }
            httpRequest = post;
        } else {
            throw new IllegalArgumentException("Unsupported method: " + method);
        }

        for (Map.Entry<String, String> header : headers.entrySet()) {
            httpRequest.setHeader(header.getKey(), header.getValue());
        }

        try (CloseableHttpResponse response = httpClient.execute(httpRequest)) {
            int statusCode = response.getStatusLine().getStatusCode();
            String responseBody = EntityUtils.toString(response.getEntity(), StandardCharsets.UTF_8);

            JsonNode jsonNode = objectMapper.readTree(responseBody);

            return new ApiResponse(
                statusCode == 200,
                statusCode,
                jsonNode.get("data"),
                jsonNode.has("message") ? jsonNode.get("message").asText() : "",
                response.getFirstHeader("X-Request-ID") != null ?
                    response.getFirstHeader("X-Request-ID").getValue() : ""
            );
        }
    }

    // ============ API方法 ============

    /**
     * 单个转债打分
     */
    public ApiResponse scoreBond(String code, String date) throws Exception {
        Map<String, String> params = null;
        if (date != null) {
            params = new HashMap<>();
            params.put("date", date);
        }
        return request("GET", "/api/v3/scoring/score/" + code, params, null);
    }

    public ApiResponse scoreBond(String code) throws Exception {
        return scoreBond(code, null);
    }

    /**
     * 批量打分
     */
    public ApiResponse scoreBonds(List<String> codes, String date) throws Exception {
        Map<String, Object> body = new HashMap<>();
        body.put("codes", codes);
        if (date != null) {
            body.put("date", date);
        }
        return request("POST", "/api/v3/scoring/score", null, body);
    }

    public ApiResponse scoreBonds(List<String> codes) throws Exception {
        return scoreBonds(codes, null);
    }

    /**
     * 获取白名单
     */
    public ApiResponse getWhitelist(String date, int topN) throws Exception {
        Map<String, String> params = new HashMap<>();
        params.put("top_n", String.valueOf(topN));
        if (date != null) {
            params.put("date", date);
        }
        return request("GET", "/api/v3/scoring/whitelist", params, null);
    }

    public ApiResponse getWhitelist() throws Exception {
        return getWhitelist(null, 60);
    }

    /**
     * 生成交易信号
     */
    public ApiResponse generateSignals(String portfolioId, String mode,
                                         Map<String, Object> constraints) throws Exception {
        Map<String, Object> body = new HashMap<>();
        if (portfolioId != null) body.put("portfolio_id", portfolioId);
        if (mode != null) body.put("mode", mode);
        if (constraints != null) body.put("constraints", constraints);
        return request("POST", "/api/v3/signals/generate", null, body);
    }

    /**
     * 获取持仓
     */
    public ApiResponse getPositions(String portfolioId) throws Exception {
        Map<String, String> params = null;
        if (portfolioId != null) {
            params = new HashMap<>();
            params.put("portfolio_id", portfolioId);
        }
        return request("GET", "/api/v3/positions", params, null);
    }

    public ApiResponse getPositions() throws Exception {
        return getPositions(null);
    }

    /**
     * 获取风险指标
     */
    public ApiResponse getRiskMetrics() throws Exception {
        return request("GET", "/api/v3/risk/metrics", null, null);
    }

    /**
     * 计算VaR
     */
    public ApiResponse calculateVar(double confidence, String method, int horizon) throws Exception {
        Map<String, Object> body = new HashMap<>();
        body.put("confidence", confidence);
        body.put("method", method);
        body.put("horizon", horizon);
        return request("POST", "/api/v3/risk/var", null, body);
    }

    /**
     * 健康检查
     */
    public ApiResponse healthCheck() throws Exception {
        return request("GET", "/api/v3/system/health", null, null);
    }

    /**
     * 关闭客户端
     */
    public void close() throws Exception {
        httpClient.close();
    }

    // ============ 工具方法 ============

    private String md5(String input) {
        try {
            MessageDigest md = MessageDigest.getInstance("MD5");
            byte[] digest = md.digest(input.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            for (byte b : digest) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    private String hmacSha256(String key, String data) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            SecretKeySpec secretKeySpec = new SecretKeySpec(key.getBytes(StandardCharsets.UTF_8), "HmacSHA256");
            mac.init(secretKeySpec);
            byte[] hmac = mac.doFinal(data.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder();
            for (byte b : hmac) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    // ============ 响应类 ============

    public static class ApiResponse {
        private final boolean success;
        private final int statusCode;
        private final JsonNode data;
        private final String message;
        private final String requestId;

        public ApiResponse(boolean success, int statusCode, JsonNode data,
                          String message, String requestId) {
            this.success = success;
            this.statusCode = statusCode;
            this.data = data;
            this.message = message;
            this.requestId = requestId;
        }

        public boolean isSuccess() { return success; }
        public int getStatusCode() { return statusCode; }
        public JsonNode getData() { return data; }
        public String getMessage() { return message; }
        public String getRequestId() { return requestId; }
    }
}
