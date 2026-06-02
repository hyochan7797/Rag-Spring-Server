package com.example.chatbotproject.service;

import com.example.chatbotproject.entity.ChatConversationSummary;
import com.example.chatbotproject.entity.ChatHistory;
import com.example.chatbotproject.repository.ChatConversationSummaryRepository;
import com.example.chatbotproject.repository.ChatHistoryRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Collections;
import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class ChatHistoryService {

    private static final int SUMMARY_TURN_LIMIT = 10;
    private static final int SUMMARY_MAX_LENGTH = 1000;

    private final ChatHistoryRepository chatHistoryRepository;
    private final ChatConversationSummaryRepository chatConversationSummaryRepository;

    @Transactional
    public void saveRagHistory(Long userId, String question, String answer) {
        chatHistoryRepository.save(new ChatHistory(userId, question, answer, true));
        refreshSummary(userId);
    }

    @Transactional
    public void saveDisplayOnlyHistory(Long userId, String question, String answer) {
        chatHistoryRepository.save(new ChatHistory(userId, question, answer, false));
    }

    private void refreshSummary(Long userId) {
        List<ChatHistory> recent = chatHistoryRepository.findRecentRagHistory(
                userId, PageRequest.of(0, SUMMARY_TURN_LIMIT));
        Collections.reverse(recent);

        String summary = recent.stream()
                .map(ChatHistory::getMessage)
                .filter(message -> message != null && !message.isBlank())
                .map(String::trim)
                .distinct()
                .collect(Collectors.joining(" / "));

        if (summary.length() > SUMMARY_MAX_LENGTH) {
            summary = summary.substring(summary.length() - SUMMARY_MAX_LENGTH);
        }
        if (!summary.isBlank()) {
            summary = "Recent user needs: " + summary;
        }
        if (summary.length() > SUMMARY_MAX_LENGTH) {
            summary = summary.substring(summary.length() - SUMMARY_MAX_LENGTH);
        }

        ChatConversationSummary conversationSummary = chatConversationSummaryRepository.findByUserId(userId)
                .orElseGet(() -> new ChatConversationSummary(userId, ""));
        conversationSummary.setSummary(summary);
        chatConversationSummaryRepository.save(conversationSummary);
    }
}
