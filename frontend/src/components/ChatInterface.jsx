import React, { useState, useRef, useEffect } from 'react';
import { aiService } from '../api';
import { useAuth } from '../context/AuthContext';

const ChatInterface = () => {
    const { user } = useAuth();
    const [isChatOpen, setIsChatOpen] = useState(false);
    const [chatMessages, setChatMessages] = useState([
        { sender: 'bot', text: 'Hello! I\'m your HealthScribe assistant. Ask me about your records.' }
    ]);
    const [userInput, setUserInput] = useState('');
    const [isWaiting, setIsWaiting] = useState(false);
    const messagesEndRef = useRef(null);

    // auto-scroll when new messages come in
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [chatMessages, isWaiting]);

    const handleSendMessage = async () => {
        const text = userInput.trim();
        if (!text) return;

        setChatMessages([...chatMessages, { sender: 'user', text }]);
        setUserInput('');
        setIsWaiting(true);

        try {
            const res = await aiService.post('/chat', {
                query: text,
                user_id: user?.id || 1
            });
            const answer = res.data.answer || 'No response from the assistant.';
            setChatMessages(prev => [...prev, { sender: 'bot', text: answer }]);
        } catch {
            setChatMessages(prev => [...prev, { sender: 'bot', text: 'Connection error. Is the AI service running?' }]);
        } finally {
            setIsWaiting(false);
        }
    };

    const handleClearChat = async () => {
        try {
            await aiService.post('/chat/clear', { user_id: user?.id || 1 });
        } catch {
            // not a big deal if clear fails
        }
        setChatMessages([{ sender: 'bot', text: 'Chat cleared. Ask me anything!' }]);
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter') handleSendMessage();
    };

    if (!isChatOpen) {
        return (
            <button onClick={() => setIsChatOpen(true)} className="chat-fab">
                💬
            </button>
        );
    }

    return (
        <div className="chat-window">
            <div className="chat-header">
                <div className="chat-header-info">
                    <span className="chat-bot-name">HealthScribe Assistant</span>
                    <span className="chat-bot-status">{user?.username}</span>
                </div>
                <div className="chat-header-actions">
                    <button onClick={handleClearChat} className="btn-close" title="Clear chat">
                        Clear
                    </button>
                    <button onClick={() => setIsChatOpen(false)} className="btn-close" title="Close">
                        ✕
                    </button>
                </div>
            </div>
            
            <div className="chat-messages">
                {chatMessages.map((msg, idx) => (
                    <div key={idx} className={`message-bubble ${msg.sender}-message`}>
                        {msg.text}
                    </div>
                ))}

                {isWaiting && (
                    <div className="message-bubble bot-message">
                        <span className="typing-dot typing-dot-1"></span>
                        <span className="typing-dot typing-dot-2"></span>
                        <span className="typing-dot typing-dot-3"></span>
                    </div>
                )}

                <div ref={messagesEndRef} />
            </div>

            <div className="chat-input-area">
                <input 
                    className="chat-input" 
                    placeholder="Ask a question..." 
                    value={userInput} 
                    onChange={e => setUserInput(e.target.value)} 
                    onKeyDown={handleKeyDown}
                    disabled={isWaiting}
                />
                <button
                    onClick={handleSendMessage}
                    disabled={isWaiting || !userInput.trim()}
                    className="btn-send"
                >
                    →
                </button>
            </div>
        </div>
    );
};

export default ChatInterface;
