import React, { useRef, useState } from 'react';

const SpotlightCard = ({ children, className = "", spotlightColor = "rgba(26, 138, 110, 0.25)" }) => {
    const divRef = useRef(null);
    const [position, setPosition] = useState({ x: 0, y: 0 });
    const [opacity, setOpacity] = useState(0);

    const handleMouseMove = (e) => {
        if (!divRef.current) return;
        const rect = divRef.current.getBoundingClientRect();
        setPosition({ x: e.clientX - rect.left, y: e.clientY - rect.top });
    };

    const handleMouseEnter = () => setOpacity(1);
    const handleMouseLeave = () => setOpacity(0);

    return (
        <div
            ref={divRef}
            onMouseMove={handleMouseMove}
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
            className={`spotlight-card ${className}`}
            style={{ position: 'relative', overflow: 'hidden' }}
        >
            <div
                className="spotlight-overlay"
                style={{
                    opacity,
                    background: `radial-gradient(350px circle at ${position.x}px ${position.y}px, ${spotlightColor}, transparent 80%)`,
                    position: 'absolute',
                    inset: 0,
                    pointerEvents: 'none',
                    transition: 'opacity 0.3s ease',
                    zIndex: 1
                }}
            />
            <div style={{ position: 'relative', zIndex: 2 }}>
                {children}
            </div>
        </div>
    );
};

export default SpotlightCard;
