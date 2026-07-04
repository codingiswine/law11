import React, { useState, useEffect } from 'react';

interface TypingEffectProps {
  text: string;
  speed?: number;
  className?: string;
}

export const TypingEffect: React.FC<TypingEffectProps> = ({ 
  text, 
  speed = 30, 
  className = "" 
}) => {
  const [displayedText, setDisplayedText] = useState('');
  const [currentIndex, setCurrentIndex] = useState(0);

  useEffect(() => {
    if (currentIndex < text.length) {
      const timeout = setTimeout(() => {
        setDisplayedText(prev => prev + text[currentIndex]);
        setCurrentIndex(prev => prev + 1);
      }, speed);

      return () => clearTimeout(timeout);
    }
  }, [currentIndex, text, speed]);

  useEffect(() => {
    if (text.length === 0) {
      if (displayedText !== '') {
        setDisplayedText('');
      }
      if (currentIndex !== 0) {
        setCurrentIndex(0);
      }
      return;
    }

    if (!text.startsWith(displayedText)) {
      if (displayedText !== '') {
        setDisplayedText('');
      }
      if (currentIndex !== 0) {
        setCurrentIndex(0);
      }
    } else if (currentIndex > text.length) {
      setDisplayedText(text);
      setCurrentIndex(text.length);
    }
  }, [text, displayedText, currentIndex]);

  return (
    <div className={className}>
      {displayedText}
      {currentIndex < text.length && (
        <span className="animate-pulse">|</span>
      )}
    </div>
  );
};
