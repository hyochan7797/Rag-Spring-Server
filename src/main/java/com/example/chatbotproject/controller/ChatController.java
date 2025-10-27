package com.example.chatbotproject.controller;

import com.example.chatbotproject.entity.ChatHistory;
import com.example.chatbotproject.repository.ChatHistoryRepository;
import com.example.chatbotproject.service.FastApiService;
import jakarta.servlet.http.HttpSession;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.*;

@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
public class ChatController {

    private final FastApiService fastApiService;
    private final ChatHistoryRepository chatHistoryRepository;
    private static final String GREETING_MESSAGE = """
안녕하세요, 대출 AI 챗봇입니다. 필요한 대출에 대한 질문을 해주세요!

📍 참고: 주변 은행 지점을 확인하려면 아래처럼 질문해 주세요.
→ '근처 국민은행 알려줘', '근처 하나은행 알려줘', '근처 우리은행 알려줘'
(정확히 일치해야 지도 기능이 활성화됩니다.)
""";

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
        // ✅ 첫 접속 시 인삿말 출력
        if (session.getAttribute("greeted") == null) {
            session.setAttribute("greeted", true);
            return ResponseEntity.ok(Map.of("answer", GREETING_MESSAGE));
        }

        // 📍 챗봇 첫 인사말 세션으로 확인
        boolean greeted = Boolean.TRUE.equals(session.getAttribute("greeted"));
        session.setAttribute("greeted", true);  // 첫 방문 여부 저장

        StringBuilder answerBuilder = new StringBuilder();



        // 📡 FastAPI 호출
        String answer = fastApiService.askFastApi(userId, question);

        // 🧠 지도 버튼 삽입 로직
        List<String> BANKS = List.of("국민은행", "하나은행", "우리은행");
        for (String bank : BANKS) {
            if (question.equals("근처 " + bank + " 알려줘")) {
                String htmlAnswer = String.format(
                        "근처 %s 지점을 확인하려면 아래 버튼을 눌러주세요.<br><br>" +
                                "<a href='/map.html?bank=%s' target='_blank' style='" +
                                "background:#2563eb;color:white;padding:8px 12px;border-radius:6px;" +
                                "text-decoration:none;display:inline-block;'>📍 지도에서 %s 보기</a>",
                        bank, bank, bank
                );

                chatHistoryRepository.save(new ChatHistory(userId, question, htmlAnswer));
                return ResponseEntity.ok(Map.of("answer", htmlAnswer));
            }
        }

        // 💾 DB 저장
        ChatHistory chat = new ChatHistory(userId, question, answer);
        chatHistoryRepository.save(chat);

        // 📤 응답 반환
        return ResponseEntity.ok(Map.of("answer", answer));
    }
}