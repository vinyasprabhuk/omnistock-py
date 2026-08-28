from __future__ import annotations

from collections import defaultdict

from flask import Blueprint, g, render_template

bp = Blueprint("recipe", __name__)


@bp.route("/recipe", methods=["GET"])
def index():
    conn = g.conn

    dish_recipes = conn.execute(
        "SELECT r.id AS recipeId, r.name, r.servesQty, r.servesVolumeLitre, r.portionSizeMl, "
        "dish.category AS category, dish.menuGroup AS menuGroup, dept.name AS departmentName "
        "FROM Recipe r JOIN Dish dish ON dish.id = r.dishId "
        "JOIN Department dept ON dept.id = dish.departmentId "
        "ORDER BY dish.menuGroup, r.name"
    ).fetchall()

    accompaniment_recipes = conn.execute(
        "SELECT id AS recipeId, name, servesQty, servesVolumeLitre, portionSizeMl "
        "FROM Recipe WHERE dishId IS NULL ORDER BY name"
    ).fetchall()

    recipe_lines = {}
    for recipe_id in [r["recipeId"] for r in dish_recipes] + [r["recipeId"] for r in accompaniment_recipes]:
        rows = conn.execute(
            "SELECT itemId, subRecipeId, qty, rawIngredientName, rawQtyValue, rawQtyUnit, matchStatus "
            "FROM RecipeLine WHERE recipeId = ?", (recipe_id,),
        ).fetchall()
        lines = []
        for r in rows:
            item_name, item_unit = None, None
            if r["itemId"]:
                item = conn.execute("SELECT name, unit FROM Item WHERE id = ?", (r["itemId"],)).fetchone()
                if item:
                    item_name, item_unit = item["name"], item["unit"]
            lines.append({**dict(r), "itemName": item_name, "itemUnit": item_unit})
        recipe_lines[recipe_id] = lines

    dishes_without_recipe_rows = conn.execute(
        "SELECT dish.id, dish.name, dish.category, dish.menuGroup AS menuGroup, "
        "(SELECT COUNT(*) FROM DishSale ds WHERE ds.dishId = dish.id) AS saleCount "
        "FROM Dish dish "
        "LEFT JOIN Recipe r ON r.dishId = dish.id "
        "WHERE r.id IS NULL AND dish.menuGroup != 'Other' AND dish.active = 1 "
        "ORDER BY saleCount DESC"
    ).fetchall()
    dishes_without_recipe_by_group: dict[str, list] = defaultdict(list)
    for row in dishes_without_recipe_rows:
        dishes_without_recipe_by_group[row["menuGroup"]].append(row)
    dishes_without_recipe_by_group = dict(
        sorted(dishes_without_recipe_by_group.items(), key=lambda kv: -len(kv[1]))
    )

    return render_template(
        "recipe/index.html", dish_recipes=dish_recipes, accompaniment_recipes=accompaniment_recipes,
        recipe_lines=recipe_lines, dishes_without_recipe_by_group=dishes_without_recipe_by_group,
    )
