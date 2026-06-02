package com.example.chatbotproject.service;

import com.example.chatbotproject.entity.ChatHistory;
import com.example.chatbotproject.repository.ChatHistoryRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class FastApiService {

    private final ChatHistoryRepository chatHistoryRepository;
    private final RestTemplate fastApiAdminRestTemplate;

    @Value("${fastapi.chat.url}")
    private String fastApiChatUrl;

    public String askFastApi(Long userId, String question) {
        List<ChatHistory> recent = chatHistoryRepository.findTop5ByUserIdOrderByTimestampDesc(userId);
        Collections.reverse(recent);

        List<Map<String, String>> history = new ArrayList<>();
        for (ChatHistory h : recent) {
            history.add(Map.of("role", "user", "content", h.getMessage()));
            history.add(Map.of("role", "model", "content", h.getResponse()));
        }

        Map<String, Object> payload = new HashMap<>();
        payload.put("user_id", userId);
        payload.put("question", question);
        payload.put("history", history);

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("ngrok-skip-browser-warning", "true");

        try {
            ResponseEntity<Map> response = fastApiAdminRestTemplate.postForEntity(
                    fastApiChatUrl, new HttpEntity<>(payload, headers), Map.class);
            Map body = response.getBody();
            if (body == null || body.get("answer") == null) {
                return "FastAPI response did not include an answer.";
            }
            return body.get("answer").toString();
        } catch (Exception e) {
            return "FastAPI response failed: " + e.getMessage();
        }
    }
}
