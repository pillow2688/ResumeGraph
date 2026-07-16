const suggestions = [
  "请介绍一下你的教育背景",
  "请介绍 ResumeGraph 项目",
  "为什么项目使用 Redis",
  "Redis 的缓存击穿是什么",
  "这个项目目前还有哪些不足",
];

interface WelcomeSuggestionsProps {
  projectNames: string[];
  onSelect: (suggestion: string) => void;
}

export function WelcomeSuggestions({
  projectNames,
  onSelect,
}: WelcomeSuggestionsProps) {
  return (
    <section className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-4 py-10 text-center sm:px-6">
      <div className="mx-auto grid size-14 place-items-center rounded-2xl border border-slate-200 bg-white text-lg font-black shadow-sm">
        RG
      </div>
      <h2 className="mt-5 text-2xl font-semibold tracking-tight sm:text-3xl">
        从一次自然的技术面试开始
      </h2>
      <p className="mx-auto mt-3 max-w-2xl text-sm leading-6 text-slate-600">
        我可以结合候选人的 Profile、授权项目事实和已发布 Technical
        资料回答问题，并明确区分当前实现、通用原理与后续方案。
      </p>
      <p className="mt-3 text-xs font-medium text-slate-500">
        当前授权项目：{projectNames.length > 0 ? projectNames.join("、") : "无项目范围"}
      </p>
      <div className="mt-7 flex flex-wrap justify-center gap-2">
        {suggestions.map((suggestion) => (
          <button
            className="rounded-full border border-slate-300 bg-white px-4 py-2.5 text-sm text-slate-700 shadow-sm hover:border-slate-400 hover:bg-slate-50"
            key={suggestion}
            onClick={() => onSelect(suggestion)}
            type="button"
          >
            {suggestion}
          </button>
        ))}
      </div>
      <p className="mt-4 text-xs text-slate-400">点击示例只会填入输入框，不会自动消耗额度。</p>
    </section>
  );
}
