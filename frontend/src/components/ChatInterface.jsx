import React, { useState, useRef, useEffect } from 'react';
import { aiService } from '../api';
import { useAuth } from '../context/AuthContext';
import { MessageCircle, X, Send, Trash2 } from 'lucide-react';

const ChatInterface = () => {
    const { user } = useAuth();
    const [isChatOpen, setIsChatOpen] = useState(false);
    const [chatMessages, setChatMessages] = useState([
        { sender: 'bot', text: 'Hello! I\'m your HealthScribe assistant. Ask me about your records.' }
    ]);
    const [userInput, setUserInput] = useState('');
    const [isWaiting, setIsWaiting] = useState(false);
    const messagesEndRef = useRef(null);

    // scroll to bottom when new messages come in
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
        } catch (e) {
            setChatMessages(prev => [...prev, { sender: 'bot', text: 'Connection error. Is the AI service running?' }]);
        } finally {
            setIsWaiting(false);
        }
    };

    const handleClearChat = async () => {
        try {
            await aiService.post('/chat/clear', { user_id: user?.id || 1 });
        } catch (e) {
            // not critical if this fails
        }
        setChatMessages([{ sender: 'bot', text: 'Chat cleared. Ask me anything!' }]);
    };

    const handleKeyDown = (e) => {
        if (e.key === 'Enter') handleSendMessage();
    };

    // show floating button when chat is closed
    if (!isChatOpen) {
        return (
            <button onClick={() => setIsChatOpen(true)} className="chat-fab">
                <MessageCircle size={22} />
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
                <div style={{ display: 'flex', gap: '6px' }}>
                    <button onClick={handleClearChat} className="btn-close" title="Clear chat">
                        <Trash2 size={15} />
                    </button>
                    <button onClick={() => setIsChatOpen(false)} className="btn-close" title="Close">
                        <X size={18} />
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
                        <span className="typing-dot" style={{ animationDelay: '0ms' }}></span>
                        <span className="typing-dot" style={{ animationDelay: '200ms' }}></span>
                        <span className="typing-dot" style={{ animationDelay: '400ms' }}></span>
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
                    <Send size={16} />
                </button>
            </div>
        </div>
    );
};

export default ChatInterface;
