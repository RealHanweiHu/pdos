"use client";

import { useState } from "react";
import { Sparkle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { Sheet } from "./product-preview-ui";
import type { ProductCategory } from "./category-preview-state";
import type { ProductController } from "./product-preview-state";
import p from "./product-preview.module.css";

export function CategoryBasics({
  controller: c,
  category,
  disabled,
  onClose,
  onSaved,
  onPai,
}: {
  controller: ProductController;
  category?: ProductCategory;
  disabled: boolean;
  onClose: () => void;
  onSaved: (id: string) => void;
  onPai: () => void;
}) {
  const [name, setName] = useState(category?.name ?? "");
  const [description, setDescription] = useState(category?.description ?? "");
  const [error, setError] = useState("");
  const unchanged =
    category &&
    name.trim() === category.name &&
    description.trim() === category.description;
  return (
    <Sheet title={category ? "编辑品类" : "新建品类"} onClose={onClose}>
      <h1>{category ? "品类信息" : "建立一个产品方向"}</h1>
      <p>
        {category
          ? "名称和主要场景会同步到品类总览与后续工作。"
          : "先确定品类与使用场景，竞品、用户声音和规格可以逐步补充。"}
      </p>
      {!category && (
        <button className={p.paiCreate} disabled={disabled} onClick={onPai}>
          <Sparkle size={15} />
          与小Pai一起创建<small>通过对话整理名称与场景</small>
        </button>
      )}
      <form
        className={p.form}
        onSubmit={(e) => {
          e.preventDefault();
          if (disabled || !c.allowed) return;
          const result = category
            ? c.updateCategory(category.id, name, description)
            : c.createCategory(name, description);
          if (result.error) setError(result.error);
          else onSaved(result.id!);
        }}
      >
        <label>
          品类名称
          <input
            autoFocus
            aria-label="品类名称"
            required
            disabled={disabled}
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setError("");
            }}
            placeholder="例如：自行车充气泵"
          />
        </label>
        <label>
          主要场景
          <textarea
            aria-label="主要场景"
            disabled={disabled}
            value={description}
            onChange={(e) => {
              setDescription(e.target.value);
              setError("");
            }}
            placeholder="描述面向谁、解决什么使用问题"
          />
        </label>
        <p className={p.note}>
          负责人：{category?.owner ?? c.person}
          {!category && " · 创建后可以逐步补充资料"}
        </p>
        {error && (
          <p className={p.formError} role="alert">
            {error}
          </p>
        )}
        <div className={p.headerActions}>
          <Button type="button" variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button
            type="submit"
            disabled={disabled || !c.allowed || !name.trim() || !!unchanged}
          >
            {category ? "保存修改" : "创建品类"}
          </Button>
        </div>
      </form>
    </Sheet>
  );
}
