package com.example.chatbotproject.service;

import org.springframework.http.*;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.*;

@Service
public class FastApiService {

    public String askFastApi(Long userId, String question) {
        String url = System.getenv("FASTAPI_URL");
        if (url == null || url.isEmpty()) {
            url = "http://localhost:8000/chat"; // fallback (로컬 실행용)
        }

        Map<String, Object> payload = new HashMap<>();
        payload.put("user_id", userId);
        payload.put("question", question);

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);

        HttpEntity<Map<String, Object>> request = new HttpEntity<>(payload, headers);
        RestTemplate restTemplate = new RestTemplate();

        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(url, request, Map.class);
            return response.getBody().get("answer").toString();
        } catch (Exception e) {
            return "FastAPI 응답 실패: " + e.getMessage();
        }
    }
}
