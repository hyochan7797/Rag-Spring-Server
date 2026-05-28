package com.example.chatbotproject.service;

import com.example.chatbotproject.entity.ChatHistory;
import com.example.chatbotproject.repository.ChatHistoryRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.http.*;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.*;

@Service
@RequiredArgsConstructor
public class FastApiService {

    private final ChatHistoryRepository chatHistoryRepository;

    public String askFastApi(Long userId, String question) {
        String url = System.getenv("FASTAPI_URL");
        if (url == null || url.isEmpty()) {
            url = "http://localhost:8000/chat";
        }

        // MySQL에서 최근 5개 대화 꺼내기 (시간 역순 → 다시 정순 정렬)
        List<ChatHistory> recent = chatHistoryRepository.findTop5ByUserIdOrderByTimestampDesc(userId);
        Collections.reverse(recent);

        List<Map<String, String>> history = new ArrayList<>();
        for (ChatHistory h : recent) {
            history.add(Map.of("role", "user",  "content", h.getMessage()));
            history.add(Map.of("role", "model", "content", h.getResponse()));
        }

        Map<String, Object> payload = new HashMap<>();
        payload.put("user_id", userId);
        payload.put("question", question);
        payload.put("history", history);   // FastAPI가 인메모리 대신 이 값을 사용

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);

        RestTemplate restTemplate = new RestTemplate();
        try {
            ResponseEntity<Map> response = restTemplate.postForEntity(
                    url, new HttpEntity<>(payload, headers), Map.class);
            return response.getBody().get("answer").toString();
        } catch (Exception e) {
            return "FastAPI 응답 실패: " + e.getMessage();
        }
    }
}
