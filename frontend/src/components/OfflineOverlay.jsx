import { useState, useEffect } from 'react';
import { WifiOff, RefreshCw } from 'lucide-react';
import './offline-overlay.css';

export default function OfflineOverlay({ onRetry }) {
  const RETRY_SECONDS = 5;
  const [timeLeft, setTimeLeft] = useState(RETRY_SECONDS);
  const [isRetrying, setIsRetrying] = useState(false);

  useEffect(() => {
    if (timeLeft <= 0) {
      handleRetry();
      return;
    }
    const timer = setTimeout(() => {
      setTimeLeft((t) => t - 1);
    }, 1000);
    return () => clearTimeout(timer);
  }, [timeLeft]);

  const handleRetry = async () => {
    setIsRetrying(true);
    await onRetry();
    // If it fails, onRetry will complete and parent state online will stay false.
    // We then reset the timer to try again.
    setTimeout(() => {
      setIsRetrying(false);
      setTimeLeft(RETRY_SECONDS);
    }, 500); // Small delay to show spinning state
  };

  return (
    <div className="offline-overlay">
      <div className="offline-modal card rise">
        <div className="offline-icon">
          <WifiOff size={48} strokeWidth={1.5} />
        </div>
        <h2 className="display">Connection Lost</h2>
        <p className="muted">
          Can't reach the extraction engine. Please ensure the backend is running on port 8000.
        </p>
        
        <div className="offline-actions">
          <button 
            className="btn btn-primary" 
            onClick={() => {
              setTimeLeft(RETRY_SECONDS); // pause countdown visually
              handleRetry();
            }} 
            disabled={isRetrying}
          >
            <RefreshCw size={16} className={isRetrying ? 'spin' : ''} />
            {isRetrying ? 'Reconnecting...' : 'Retry Now'}
          </button>
        </div>
        
        <p className="offline-countdown mono muted">
          {!isRetrying && `Retrying automatically in ${timeLeft}s...`}
          {isRetrying && 'Attempting to reconnect...'}
        </p>
      </div>
    </div>
  );
}
