import React, { useState, useEffect } from 'react';

const TypewriterText = ({ 
    phrases = [
        'digitized & searchable.',
        'organized in seconds.',
        'always at your fingertips.'
    ], 
    typingSpeed = 70, 
    deletingSpeed = 40, 
    pauseDuration = 2000 
}) => {
    const [phraseIndex, setPhraseIndex] = useState(0);
    const [currentText, setCurrentText] = useState('');
    const [isDeleting, setIsDeleting] = useState(false);

    useEffect(() => {
        const targetPhrase = phrases[phraseIndex];

        let timer;
        if (!isDeleting && currentText === targetPhrase) {
            // Pause before starting to delete
            timer = setTimeout(() => setIsDeleting(true), pauseDuration);
        } else if (isDeleting && currentText === '') {
            // Move to next phrase after deleting
            setIsDeleting(false);
            setPhraseIndex((prevIndex) => (prevIndex + 1) % phrases.length);
        } else {
            // Type or delete characters
            const speed = isDeleting ? deletingSpeed : typingSpeed;
            timer = setTimeout(() => {
                setCurrentText((prev) =>
                    isDeleting
                        ? targetPhrase.substring(0, prev.length - 1)
                        : targetPhrase.substring(0, prev.length + 1)
                );
            }, speed);
        }

        return () => clearTimeout(timer);
    }, [currentText, isDeleting, phraseIndex, phrases, typingSpeed, deletingSpeed, pauseDuration]);

    return (
        <span className="typewriter-container">
            <span className="typewriter-text">{currentText}</span>
            <span className="typewriter-cursor">|</span>
        </span>
    );
};

export default TypewriterText;
