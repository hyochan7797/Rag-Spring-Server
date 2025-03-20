package com.example.chatbotproject.entity;

import jakarta.persistence.*;
import lombok.*;

import java.time.LocalDateTime;

@Entity  // 데이터베이스 테이블과 매핑
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
@Table(name = "users") // 실제 DB 테이블 이름 설정
public class User {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY) // 기본 키 자동 생성
    private Long id;

    @Column(unique = true, nullable = false) // 이메일은 고유하고 null이 될 수 없음
    private String email;

    @Column(nullable = false) // null이 될 수 없음
    private String username;

    @Column(nullable = false) // null이 될 수 없음
    private String password;

    @Column(nullable = false, updatable = false) // null이 될 수 없고 수정 불가
    private LocalDateTime createdAt = LocalDateTime.now(); // 현재 시간 자동 저장
}