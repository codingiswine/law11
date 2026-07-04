import React from "react";

const LoadingDots: React.FC = () => {
  return (
    <div className="flex justify-start items-center mt-2 ml-2 space-x-1 animate-pulse">
      <span className="w-2 h-2 bg-gray-400 rounded-full"></span>
      <span className="w-2 h-2 bg-gray-400 rounded-full"></span>
      <span className="w-2 h-2 bg-gray-400 rounded-full"></span>
    </div>
  );
};

export default LoadingDots;
