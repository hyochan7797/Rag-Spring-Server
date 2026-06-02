package com.example.chatbotproject.service;

import com.example.chatbotproject.entity.ChatHistory;
import com.example.chatbotproject.repository.ChatConversationSummaryRepository;
import com.example.chatbotproject.repository.ChatHistoryRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class FastApiService {

    private static final int HISTORY_TURN_LIMIT = 5;
    private static final int MAX_HISTORY_MESSAGE_LENGTH = 500;
    private static final int MAX_HISTORY_RESPONSE_LENGTH = 1000;

    private final ChatHistoryRepository chatHistoryRepository;
    private final ChatConversationSummaryRepository chatConversationSummaryRepository;
    private final RestTemplate fastApiAdminRestTemplate;

    @Value("${fastapi.chat.url}")
    private String fastApiChatUrl;

    public String askFastApi(Long userId, String question) {
        List<ChatHistory> recent = chatHistoryRepository.findRecentRagHistory(
                userId, PageRequest.of(0, HISTORY_TURN_LIMIT));
        Collections.reverse(recent);

        List<Map<String, String>> history = new ArrayList<>();
        for (ChatHistory h : recent) {
            String message = truncate(h.getMessage(), MAX_HISTORY_MESSAGE_LENGTH);
            String response = truncate(h.getResponse(), MAX_HISTORY_RESPONSE_LENGTH);
            if (message.isBlank() || response.isBlank()) {
                continue;
            }
            history.add(Map.of("role", "user", "content", message));
            history.add(Map.of("role", "model", "content", response));
        }

        Map<String, Object> payload = new HashMap<>();
        payload.put("user_id", userId);
        payload.put("question", question);
        payload.put("history", history);
        chatConversationSummaryRepository.findByUserId(userId)
                .map(summary -> truncate(summary.getSummary(), MAX_HISTORY_RESPONSE_LENGTH))
                .filter(summary -> !summary.isBlank())
                .ifPresent(summary -> payload.put("history_summary", summary));

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("ngrok-skip-browser-warning", "true");

        try {
            ResponseEntity<Map> response = fastApiAdminRestTemplate.postForEntity(
                    fastApiChatUrl, new HttpEntity<>(payload, headers), Map.class);
            Map body = response.getBody();
            if (body == null || body.get("answer") == null) {
                throw new IllegalStateException("FastAPI response did not include an answer.");
            }
            return body.get("answer").toString();
        } catch (RestClientException | IllegalStateException e) {
            throw new IllegalStateException("FastAPI response failed.", e);
        }
    }

    private String truncate(String value, int maxLength) {
        if (value == null) {
            return "";
        }
        String trimmed = value.trim();
        if (trimmed.length() <= maxLength) {
            return trimmed;
        }
        return trimmed.substring(trimmed.length() - maxLength);
    }
}
