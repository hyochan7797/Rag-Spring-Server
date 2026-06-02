package com.example.chatbotproject.controller;

import com.example.chatbotproject.entity.ChatHistory;
import com.example.chatbotproject.repository.ChatHistoryRepository;
import com.example.chatbotproject.service.FastApiService;
import jakarta.servlet.http.HttpSession;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
public class ChatController {

    private final FastApiService fastApiService;
    private final ChatHistoryRepository chatHistoryRepository;

    @PostMapping("/ask")
    public ResponseEntity<Map<String, String>> askRag(@RequestBody Map<String, String> body, HttpSession session) {
        Long userId = (Long) session.getAttribute("userId");

        if (userId == null) {
            return ResponseEntity.status(401).body(Map.of("error", "로그인이 필요합니다."));
        }

        String question = body.get("question");
        if (question == null || question.isBlank()) {
            return ResponseEntity.badRequest().body(Map.of("error", "질문이 비어 있습니다."));
        }

        List<String> banks = List.of("국민은행", "하나은행", "우리은행");
        for (String bank : banks) {
            if (question.equals("근처 " + bank + " 알려줘")) {
                String htmlAnswer = String.format(
                        "근처 %s 지점을 확인하려면 아래 버튼을 눌러주세요.<br><br>" +
                                "<a href='/map.html?bank=%s' target='_blank' style='" +
                                "background:#2563eb;color:white;padding:8px 12px;border-radius:6px;" +
                                "text-decoration:none;display:inline-block;'>지도에서 %s 보기</a>",
                        bank, bank, bank
                );

                chatHistoryRepository.save(new ChatHistory(userId, question, htmlAnswer));
                return ResponseEntity.ok(Map.of("answer", htmlAnswer));
            }
        }

        String answer = fastApiService.askFastApi(userId, question);
        chatHistoryRepository.save(new ChatHistory(userId, question, answer));

        return ResponseEntity.ok(Map.of("answer", answer));
    }
}
