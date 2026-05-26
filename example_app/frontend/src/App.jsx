import React, { useState } from 'react';

export default function App() {
  const [clickedTimes, setClickedTimes] = useState(0);

  const handleButtonClick = () => {
    const nextCount = clickedTimes + 1;
    setClickedTimes(nextCount);
    
    // Core user requirement: Console.log on button click
    console.log(`Hello World! Button clicked ${nextCount} time(s).`);
  };

  return (
    <div className="container">
      <div className="icon">🚀</div>
      <h1>Anti Gravity Demo App</h1>
      <p className="subtitle">High-Performance Frontend Microservice</p>
      
      <div className="button-group" style={{ justifyContent: 'center' }}>
        <button onClick={handleButtonClick} style={{ width: '100%', maxWidth: '300px' }}>
          Click Me (Trigger Console Log)
        </button>
      </div>

      <div className="status-box">
        <p>Console Log Action</p>
        <div className="content" style={{ color: clickedTimes > 0 ? '#38bdf8' : 'inherit', textAlign: 'center' }}>
          {clickedTimes > 0 
            ? `Logged text to console ${clickedTimes} time(s)!` 
            : 'Click the button above to log a message to the console.'}
        </div>
      </div>
    </div>
  );
}
