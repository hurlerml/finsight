import { FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Pencil, Plus } from "lucide-react";

import {
  api,
  type Category,
  type CategoryColorKey,
  type CategoryIconKey,
  type Tag,
} from "@/api/client";
import { BackPageHeader } from "@/components/BackPageHeader";
import { Button, Card, Input, Select, Textarea } from "@/components/ui";
import { categoryColor } from "@/lib/colors";
import { CategoryIcon } from "@/lib/icons";

const TAG_COLORS = ["#b8cbee", "#bfd4ae", "#ead39d", "#e7bcae", "#cfc2e4", "#b6d5d0"];
const CATEGORY_COLORS: CategoryColorKey[] = [
  "health",
  "groceries",
  "housing",
  "dining",
  "mobility",
  "subscriptions",
  "shopping",
  "leisure",
  "travel",
  "family",
  "education",
  "savings",
  "finance",
  "income",
  "other",
];
const CATEGORY_ICONS: CategoryIconKey[] = [
  "house",
  "basket",
  "utensils",
  "car",
  "heart",
  "repeat",
  "bag",
  "culture",
  "plane",
  "users",
  "education",
  "savings",
  "finance",
  "income",
  "other",
];

type CategoryDraft = {
  name: string;
  description: string;
  color_key: CategoryColorKey;
  icon: CategoryIconKey;
};

const EMPTY_CATEGORY: CategoryDraft = {
  name: "",
  description: "",
  color_key: "housing",
  icon: "other",
};

export function CategoriesPage() {
  const { t } = useTranslation();
  const [categories, setCategories] = useState<Category[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [name, setName] = useState("");
  const [tagType, setTagType] = useState<Tag["tag_type"]>("general");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [categoryFeedback, setCategoryFeedback] = useState<string | null>(null);
  const [categoryEditor, setCategoryEditor] = useState<Category | "new" | null>(null);
  const [categoryDraft, setCategoryDraft] = useState<CategoryDraft>(EMPTY_CATEGORY);
  const [categorySaving, setCategorySaving] = useState(false);

  const load = () => {
    Promise.all([api.categories(), api.tags()])
      .then(([cats, loadedTags]) => {
        setCategories(cats);
        setTags(loadedTags);
        setError(null);
      })
      .catch((err: Error) => setError(err.message));
  };

  useEffect(load, []);

  const openCategoryEditor = (category?: Category) => {
    setCategoryFeedback(null);
    setError(null);
    if (category) {
      setCategoryEditor(category);
      setCategoryDraft({
        name: category.name,
        description: category.description,
        color_key: category.color_key,
        icon: category.icon,
      });
      return;
    }
    setCategoryEditor("new");
    setCategoryDraft(EMPTY_CATEGORY);
  };

  const saveCategory = async (event: FormEvent) => {
    event.preventDefault();
    if (!categoryDraft.name.trim() || !categoryDraft.description.trim() || categorySaving) return;
    const existing = categoryEditor !== "new" ? categoryEditor : null;
    setCategorySaving(true);
    setError(null);
    try {
      const body = {
        ...categoryDraft,
        name: categoryDraft.name.trim(),
        description: categoryDraft.description.trim(),
      };
      if (existing) {
        await api.updateCategory(existing.id, body);
      } else {
        await api.createCategory(body);
      }
      setCategoryFeedback(t("categories.saved"));
      setCategoryEditor(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("categories.saveFailed"));
    } finally {
      setCategorySaving(false);
    }
  };

  const removeCategory = async () => {
    if (!categoryEditor || categoryEditor === "new" || categorySaving) return;
    try {
      const impact = await api.categoryImpact(categoryEditor.id);
      if (!window.confirm(t("categories.deleteConfirm", {
        name: categoryEditor.name,
        count: impact.assigned,
        manual: impact.manual,
      }))) return;
      setCategorySaving(true);
      const result = await api.deleteCategory(categoryEditor.id);
      setCategoryFeedback(t("categories.deletedAndQueued", {
        count: result.reset_count,
        queued: result.queued_for_agent,
      }));
      setCategoryEditor(null);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("categories.deleteFailed"));
    } finally {
      setCategorySaving(false);
    }
  };

  const createTag = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      await api.createTag({
        name: name.trim(),
        tag_type: tagType,
        color: TAG_COLORS[tags.length % TAG_COLORS.length],
        from_date: fromDate || null,
        to_date: toDate || null,
      });
      setName("");
      setTagType("general");
      setFromDate("");
      setToDate("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("tags.createFailed"));
    }
  };

  const removeTag = async (tag: Tag) => {
    try {
      await api.deleteTag(tag.id);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("tags.deleteFailed"));
    }
  };

  return (
    <div className="space-y-6">
      <BackPageHeader title={t("categories.title")} />
      <Card className="space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">{t("categories.manageTitle")}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{t("categories.manageHint")}</p>
          </div>
          <Button className="h-9 shrink-0 gap-1.5 px-3" onClick={() => openCategoryEditor()}>
            <Plus className="h-4 w-4" aria-hidden />
            {t("categories.add")}
          </Button>
        </div>
        <div className="flex flex-wrap gap-2">
          {categories.map((category) => {
            const content = (
              <>
                <span
                  className="grid h-6 w-6 shrink-0 place-items-center rounded-full text-slate-800"
                  style={{ backgroundColor: categoryColor(category.slug, category.color_key, category.color) }}
                >
                  <CategoryIcon slug={category.slug} icon={category.icon} className="h-3.5 w-3.5" />
                </span>
                <span>{category.name}</span>
                {!category.is_system && <Pencil className="h-3 w-3 opacity-45" aria-hidden />}
              </>
            );
            return category.is_system ? (
              <span
                key={category.id}
                title={category.description}
                className="inline-flex items-center gap-2 rounded-full bg-muted/45 px-3 py-1 text-sm font-medium text-foreground"
              >
                {content}
              </span>
            ) : (
              <button
                key={category.id}
                type="button"
                title={category.description}
                className="inline-flex items-center gap-2 rounded-full bg-muted/45 px-3 py-1 text-sm font-medium text-foreground transition hover:bg-muted/70"
                onClick={() => openCategoryEditor(category)}
              >
                {content}
              </button>
            );
          })}
        </div>
        {categoryFeedback && <p className="text-sm text-accent">{categoryFeedback}</p>}
        {error && <p className="mt-3 text-sm text-danger">{error}</p>}
      </Card>

      <Card className="space-y-4">
        <div>
          <h3 className="text-xl font-semibold">{t("tags.title")}</h3>
        </div>

        {tags.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {tags.map((tag) => (
              <span
                key={tag.id}
                className="inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium text-slate-800"
                style={{ backgroundColor: tag.color }}
              >
                <span>{tag.name}</span>
                {(tag.from_date || tag.to_date) && (
                  <span className="opacity-65">
                    {tag.from_date || "…"} – {tag.to_date || "…"}
                  </span>
                )}
                <button
                  type="button"
                  className="-mr-1 opacity-55 transition hover:opacity-100"
                  aria-label={t("tags.remove", { name: tag.name })}
                  onClick={() => void removeTag(tag)}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        <form className="grid gap-2 sm:grid-cols-2" onSubmit={createTag}>
          <Input
            className="sm:col-span-2"
            placeholder={t("tags.namePlaceholder")}
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
          <Select value={tagType} onChange={(event) => setTagType(event.target.value as Tag["tag_type"])}>
            <option value="general">{t("tags.types.general")}</option>
            <option value="trip">{t("tags.types.trip")}</option>
            <option value="project">{t("tags.types.project")}</option>
          </Select>
          <div className="hidden sm:block" />
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">{t("tags.from")}</label>
            <Input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} />
          </div>
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">{t("tags.to")}</label>
            <Input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} />
          </div>
          <Button className="sm:col-span-2 sm:w-fit" type="submit">{t("tags.create")}</Button>
        </form>

      </Card>

      {categoryEditor && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-4 backdrop-blur-sm"
          onMouseDown={(event) => {
            if (!categorySaving && event.target === event.currentTarget) setCategoryEditor(null);
          }}
        >
          <form
            role="dialog"
            aria-modal="true"
            aria-labelledby="category-editor-title"
            className="max-h-[calc(100dvh-2rem)] w-full max-w-md space-y-4 overflow-y-auto rounded-[1.5rem] border border-border/55 bg-background/95 p-5 shadow-2xl"
            onSubmit={saveCategory}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 id="category-editor-title" className="text-lg font-semibold">
                  {categoryEditor === "new" ? t("categories.createTitle") : t("categories.editTitle")}
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">{t("categories.editorHint")}</p>
              </div>
              <Button
                type="button"
                variant="ghost"
                className="h-8 w-8 rounded-full p-0"
                disabled={categorySaving}
                onClick={() => setCategoryEditor(null)}
                aria-label={t("common.close")}
              >×</Button>
            </div>

            <label className="block space-y-1.5 text-xs text-muted-foreground">
              <span>{t("categories.name")}</span>
              <Input
                autoFocus
                value={categoryDraft.name}
                onChange={(event) => setCategoryDraft((value) => ({ ...value, name: event.target.value }))}
                disabled={categorySaving}
                required
              />
            </label>
            <label className="block space-y-1.5 text-xs text-muted-foreground">
              <span>{t("categories.description")}</span>
              <Textarea
                value={categoryDraft.description}
                onChange={(event) => setCategoryDraft((value) => ({ ...value, description: event.target.value }))}
                disabled={categorySaving}
                placeholder={t("categories.descriptionPlaceholder")}
                required
              />
              <span className="block leading-relaxed">{t("categories.descriptionHint")}</span>
            </label>

            <fieldset className="space-y-2">
              <legend className="text-xs text-muted-foreground">{t("categories.color")}</legend>
              <div className="flex flex-wrap gap-2">
                {CATEGORY_COLORS.map((colorKey) => (
                  <button
                    key={colorKey}
                    type="button"
                    aria-label={colorKey}
                    aria-pressed={categoryDraft.color_key === colorKey}
                    className={`h-8 w-8 rounded-full border-2 transition ${categoryDraft.color_key === colorKey ? "scale-110 border-foreground" : "border-transparent"}`}
                    style={{ backgroundColor: categoryColor(colorKey) }}
                    onClick={() => setCategoryDraft((value) => ({ ...value, color_key: colorKey }))}
                  />
                ))}
              </div>
            </fieldset>

            <fieldset className="space-y-2">
              <legend className="text-xs text-muted-foreground">{t("categories.icon")}</legend>
              <div className="grid grid-cols-8 gap-1.5">
                {CATEGORY_ICONS.map((icon) => (
                  <button
                    key={icon}
                    type="button"
                    aria-label={icon}
                    aria-pressed={categoryDraft.icon === icon}
                    className={`grid aspect-square place-items-center rounded-xl border transition ${categoryDraft.icon === icon ? "border-foreground bg-muted/80" : "border-border/35 hover:bg-muted/45"}`}
                    onClick={() => setCategoryDraft((value) => ({ ...value, icon }))}
                  >
                    <CategoryIcon slug="other" icon={icon} className="h-4 w-4" />
                  </button>
                ))}
              </div>
            </fieldset>

            <div className="flex items-center justify-between gap-2 pt-1">
              <div>
                {categoryEditor !== "new" && (
                  <Button
                    type="button"
                    variant="ghost"
                    className="text-danger hover:bg-danger/10"
                    disabled={categorySaving}
                    onClick={() => void removeCategory()}
                  >
                    {t("common.delete")}
                  </Button>
                )}
              </div>
              <div className="flex gap-2">
                <Button type="button" variant="ghost" disabled={categorySaving} onClick={() => setCategoryEditor(null)}>
                  {t("common.cancel")}
                </Button>
                <Button type="submit" className="gap-2" disabled={categorySaving || !categoryDraft.name.trim() || !categoryDraft.description.trim()}>
                  {categorySaving && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
                  {t("common.save")}
                </Button>
              </div>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
