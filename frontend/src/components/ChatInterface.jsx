import React, { useState, useRef, useEffect } from 'react';
import { aiService } from '../api';
import { useAuth } from '../context/AuthContext';

const ChatInterface = () => {
    const { user } = useAuth();
    const [isChatOpen, setIsChatOpen] = useState(false);
    const [chatMessages, setChatMessages] = useState([
        { sender: 'bot', text: "Hello! I'm your HealthScribe assistant. Ask me about your records." }
    ]);
    const [userInput, setUserInput] = useState('');
    const [isWaiting, setIsWaiting] = useState(false);
    const messagesEndRef = useRef(null);

    // auto-scroll when new messages arrive or stream updates
    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [chatMessages, isWaiting]);

    const handleSendMessage = async () => {
        const text = userInput.trim();
        if (!text || isWaiting) return;

        setChatMessages(prev => [...prev, { sender: 'user', text }]);
        setUserInput('');
        setIsWaiting(true);

        const baseUrl = (aiService.defaults.baseURL || 'http://localhost:8001/').replace(/\/$/, '');
        let accumulatedText = '';
        let botMessageAdded = false;

        try {
            const response = await fetch(`${baseUrl}/chat/stream`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    query: text,
                    user_id: user?.id || 1
                })
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `Server returned ${response.status}`);
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder('utf-8');
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    const trimmed = line.trim();
                    if (!trimmed || !trimmed.startsWith('data:')) continue;

                    const dataStr = trimmed.replace(/^data:\s*/, '');
                    if (dataStr === '[DONE]') break;

                    try {
                        const parsed = JSON.parse(dataStr);
                        if (parsed.error) {
                            throw new Error(parsed.error);
                        }
                        if (parsed.chunk) {
                            accumulatedText += parsed.chunk;
                            if (!botMessageAdded) {
                                botMessageAdded = true;
                                setIsWaiting(false);
                                setChatMessages(prev => [...prev, { sender: 'bot', text: accumulatedText }]);
                            } else {
                                setChatMessages(prev => {
                                    const updated = [...prev];
                                    updated[updated.length - 1] = {
                                        sender: 'bot',
                                        text: accumulatedText
                                    };
                                    return updated;
                                });
                            }
                        }
                    } catch (parseErr) {
                        if (parseErr.message && !parseErr.message.includes('JSON')) {
                            throw parseErr;
                        }
                    }
                }
            }

            if (!botMessageAdded) {
                setIsWaiting(false);
                setChatMessages(prev => [...prev, { sender: 'bot', text: 'No response received from assistant.' }]);
            }

        } catch (error) {
            console.error('Streaming chat failed, falling back to standard endpoint:', error);
            // Fallback to standard /chat endpoint via aiService if streaming endpoint fails
            if (!botMessageAdded) {
                try {
                    const res = await aiService.post('/chat', {
                        query: text,
                        user_id: user?.id || 1
                    });
                    const answer = res.data.answer || 'No response from the assistant.';
                    setChatMessages(prev => [...prev, { sender: 'bot', text: answer }]);
                } catch (fallbackError) {
                    setChatMessages(prev => [
                        ...prev,
                        { sender: 'bot', text: fallbackError.friendlyMessage || error.message || 'Connection error. Is the AI service running?' }
                    ]);
                }
            } else {
                setChatMessages(prev => {
                    const updated = [...prev];
                    updated[updated.length - 1] = {
                        sender: 'bot',
                        text: accumulatedText ? `${accumulatedText}\n\n[Connection lost]` : (error.message || 'Error')
                    };
                    return updated;
                });
            }
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
