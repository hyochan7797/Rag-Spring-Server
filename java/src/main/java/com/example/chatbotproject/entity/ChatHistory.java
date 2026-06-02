package com.example.chatbotproject.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.sql.Timestamp;

@Entity
@Getter
@Setter
@NoArgsConstructor
public class ChatHistory {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private Long userId;

    @Column(columnDefinition = "TEXT")
    private String message;

    @Column(columnDefinition = "TEXT")
    private String response;

    private Boolean ragEligible = true;

    @CreationTimestamp
    private Timestamp timestamp;

    public ChatHistory(Long userId, String message, String response) {
        this(userId, message, response, true);
    }

    public ChatHistory(Long userId, String message, String response, boolean ragEligible) {
        this.userId = userId;
        this.message = message;
        this.response = response;
        this.ragEligible = ragEligible;
    }
}
