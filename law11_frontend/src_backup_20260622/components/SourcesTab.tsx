import React from 'react';
import type { Source } from '../types';

interface SourcesTabProps {
  sources: Source[];
}

export const SourcesTab: React.FC<SourcesTabProps> = ({ sources }) => {
  if (sources.length === 0) {
    return (
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="flex items-center gap-2 mb-4">
          <div className="w-2 h-2 bg-green-500 rounded-full"></div>
          <h2 className="text-lg font-semibold text-gray-900">Sources</h2>
        </div>
        <p className="text-gray-500">출처 정보가 없습니다.</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-2 h-2 bg-green-500 rounded-full"></div>
        <h2 className="text-lg font-semibold text-gray-900">Sources</h2>
        <span className="text-sm text-gray-500">({sources.length})</span>
      </div>
      
      <div className="space-y-4">
        {sources.map((source, index) => (
          <div key={index} className="border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow">
            <div className="flex items-start justify-between mb-2">
              <h3 className="font-medium text-gray-900 line-clamp-2">
                {source.title}
              </h3>
              <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
                {Math.round((source.relevance || source.similarity) * 100)}%
              </span>
            </div>
            
            <p className="text-sm text-gray-600 mb-3 line-clamp-2">
              {source.summary || source.text}
            </p>
            
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-500">{source.domain || source.law_name}</span>
              {source.link && (
                <a
                  href={source.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-blue-600 hover:text-blue-800 underline"
                >
                  원문 보기 →
                </a>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
