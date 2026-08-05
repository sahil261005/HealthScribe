import React from 'react';

const ShinyText = ({ text, disabled = false, speed = 3, className = '' }) => {
    return (
        <span
            className={`shiny-text ${disabled ? 'disabled' : ''} ${className}`}
            style={{ animationDuration: `${speed}s` }}
        >
            {text}
        </span>
    );
};

export default ShinyText;
