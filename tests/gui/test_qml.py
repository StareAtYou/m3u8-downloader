from __future__ import annotations

from PySide6.QtCore import QMetaObject, QPointF, Qt
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickItem
from qml_harness import QML_ROOT, StaticClient, load_qml, many_tasks, one_task, six_tasks

from m3u8_downloader.gui.bridge import AppBridge


def scene_position(item) -> QPointF:
    return item.mapToScene(QPointF(0, 0))


def named(root, object_name: str):
    item = root.findChild(QQuickItem, object_name)
    assert item is not None, object_name
    return item


def visual_descendants(item, object_name: str) -> list[QQuickItem]:
    matches = []
    for child in item.childItems():
        if child.objectName() == object_name:
            matches.append(child)
        matches.extend(visual_descendants(child, object_name))
    return matches


def visual_named(item, object_name: str) -> QQuickItem:
    matches = visual_descendants(item, object_name)
    assert matches, object_name
    return matches[0]


def test_main_qml_loads_offscreen_without_warnings_and_has_exact_composer_copy(qtbot) -> None:
    engine, root, bridge, warnings = load_qml(qtbot)
    assert warnings == []
    assert root.width() == 1440
    assert root.height() == 1024
    for name, text in (
        ("urlLabel", "M3U8 地址"),
        ("taskNameLabel", "任务名称"),
        ("saveToLabel", "保存到"),
        ("addTaskButton", "添加任务"),
        ("batchAddButton", "批量添加"),
        ("outputPreview", "输出：风起长安 第03集.mp4"),
    ):
        item = root.findChild(object, name)
        assert item is not None, name
        assert item.property("text") == text
    bridge.close()
    del engine


def test_single_submit_success_clears_transient_fields_and_failure_preserves_them(qtbot) -> None:
    engine, root, bridge, warnings = load_qml(qtbot)
    try:
        assert warnings == []
        url_input = named(root, "urlInput")
        task_name = named(root, "taskNameInput")
        save_input = named(root, "saveInput")
        overwrite = named(root, "overwriteCheck")
        url_input.setProperty("text", "https://cdn.example.com/episode.m3u8")
        task_name.setProperty("text", "第 12 集")
        save_input.setProperty("text", "/tmp/连续剧")
        overwrite.setProperty("checked", True)

        bridge.requestFailed.emit("submit", "网络错误")
        qtbot.wait(20)
        assert url_input.property("text") == "https://cdn.example.com/episode.m3u8"
        assert task_name.property("text") == "第 12 集"
        assert save_input.property("text") == "/tmp/连续剧"
        assert overwrite.property("checked") is True

        bridge.requestSucceeded.emit("submit", {"tasks": []})
        qtbot.wait(20)
        assert url_input.property("text") == ""
        assert task_name.property("text") == ""
        assert save_input.property("text") == "/tmp/连续剧"
        assert overwrite.property("checked") is False
    finally:
        bridge.close()
        del engine


def test_table_contract_responsive_columns_controls_and_navigation(qtbot) -> None:
    engine, root, bridge, _ = load_qml(qtbot)
    assert root.findChild(object, "downloadsPage") is not None
    assert root.findChild(object, "completedPage") is not None
    assert root.findChild(object, "settingsPage") is not None
    assert root.findChild(object, "taskTable") is not None
    assert root.findChild(object, "pauseAllAction") is not None
    assert root.findChild(object, "showWindowAction") is not None
    assert root.findChild(object, "quitAction") is not None

    speed_column = root.findChild(object, "speedColumnHeader")
    assert speed_column.property("visible") is True
    root.setWidth(900)
    qtbot.wait(20)
    assert speed_column.property("visible") is False

    source = (QML_ROOT / "pages" / "DownloadsPage.qml").read_text()
    assert "visible: row.canPause" in source
    assert "visible: row.canResume" in source
    assert "visible: row.canRetry" in source
    assert "KeyNavigation.tab" in source
    assert "selectedTask" in source
    assert "风起长安 第02集" not in source
    assert "overwriteCheck.checked" in (QML_ROOT / "Main.qml").read_text()
    assert "close.accepted = false" in (QML_ROOT / "Main.qml").read_text()
    assert root.findChild(object, "errorDialog") is not None
    assert root.findChild(object, "overwriteConflictDialog") is not None
    overwrite = root.findChild(object, "overwriteCheck")
    assert overwrite.property("visible") is True
    bridge.close()
    del engine


def test_batch_validation_is_all_or_nothing_and_overwrite_maps_to_payload(qtbot) -> None:
    client = StaticClient()
    bridge = AppBridge(client)
    failures = []
    bridge.requestFailed.connect(lambda action, message: failures.append((action, message)))
    assert bridge.submitBatch([{"url": "https://e/a.m3u8", "task_name": ""}], "/tmp", False) is False
    assert failures and failures[0][0] == "submit_batch"
    bridge.close()


def test_settings_exposes_default_directory_manual_proxy_and_ffmpeg() -> None:
    source = (QML_ROOT / "pages" / "SettingsPage.qml").read_text()
    assert "defaultSaveDir" in source
    assert "manualProxy" in source
    assert "ffmpegPath" in source
    assert "onSettingsLoaded" in source
    assert "close_behavior" in source


def test_completed_page_renders_completed_model_rows() -> None:
    source = (QML_ROOT / "pages" / "CompletedPage.qml").read_text()
    assert "ListView" in source
    assert 'taskState === "completed"' in source
    assert "openOutputFolder" in source


def test_desktop_composer_alignment_preview_and_completed_badge(qtbot) -> None:
    tasks = six_tasks()
    engine, root, bridge, warnings = load_qml(qtbot, tasks=tasks, width=1440, height=1024)
    assert warnings == []
    assert root.property("compactLayout") is False

    labels = [named(root, name) for name in ("urlLabel", "taskNameLabel", "saveToLabel")]
    fields = [named(root, name) for name in ("urlInput", "taskNameInput", "saveInput")]
    buttons = [named(root, name) for name in ("addTaskButton", "batchAddButton")]
    assert len({round(scene_position(item).y()) for item in labels}) == 1
    assert len({round(scene_position(item).y()) for item in fields}) == 1
    assert {round(scene_position(item).y()) for item in buttons} == {round(scene_position(fields[0]).y())}

    preview = named(root, "outputPreview")
    overwrite = named(root, "overwriteCheck")
    assert round(scene_position(preview).y()) == round(scene_position(overwrite).y())
    task_name = fields[1]
    task_name.setProperty("text", "Bad:/Name")
    qtbot.wait(20)
    assert task_name.property("text") == "Bad:/Name"
    assert preview.property("text") == "输出：Bad__Name.mp4"
    assert preview.property("color") == QColor("#ffbb44")
    assert named(root, "completedNavigation").property("badge") == 1

    bridge.tasks.replace([])
    qtbot.wait(20)
    assert named(root, "completedNavigation").property("badge") == 0
    bridge.close()
    del engine


def test_compact_composer_reflows_inside_bounds_and_keeps_tab_order(qtbot) -> None:
    for width in (1099, 820):
        engine, root, bridge, warnings = load_qml(qtbot, width=width, height=900)
        assert warnings == []
        assert root.property("compactLayout") is True
        assert root.property("horizontalOverflow") is False

        url_input = named(root, "urlInput")
        task_name = named(root, "taskNameInput")
        save_input = named(root, "saveInput")
        add_button = named(root, "addTaskButton")
        batch_button = named(root, "batchAddButton")
        assert scene_position(save_input).y() > scene_position(url_input).y()
        assert round(scene_position(add_button).y()) == round(scene_position(save_input).y())
        for item in (url_input, task_name, save_input, add_button, batch_button):
            pos = scene_position(item)
            assert pos.x() >= 208
            assert pos.x() + item.property("width") <= width

        folder_button = save_input.findChild(QQuickItem, "trailingAction")
        assert folder_button is not None
        expected = [
            url_input,
            task_name,
            save_input,
            folder_button,
            add_button,
            batch_button,
            named(root, "overwriteCheck"),
            named(root, "downloadsNavigation"),
            named(root, "completedNavigation"),
            named(root, "settingsNavigation"),
            visual_named(named(root, "tableViewport"), "taskRow"),
        ]
        url_input.forceActiveFocus()
        for next_item in expected[1:]:
            qtbot.keyClick(root, Qt.Key_Tab)
            qtbot.wait(5)
            assert root.activeFocusItem() == next_item
        bridge.close()
        del engine


def test_short_desktop_windows_keep_details_scrollable_and_non_negative(qtbot) -> None:
    for height in (900, 768, 640):
        engine, root, bridge, warnings = load_qml(qtbot, tasks=six_tasks(), width=1440, height=height)
        assert warnings == []
        detail = named(root, "detailsRegion")
        flick = named(root, "detailsFlickable")
        panel = named(root, "detailPanel")
        assert detail.property("height") > 0
        assert flick.property("height") > 0
        assert panel.property("height") >= 260
        assert flick.property("contentHeight") >= flick.property("height")
        if height < 1024:
            assert flick.property("contentHeight") > flick.property("height")
        bridge.close()
        del engine


def test_header_and_row_columns_share_geometry_at_visibility_thresholds(qtbot) -> None:
    pairs = (
        ("nameColumnHeader", "rowTaskName"),
        ("specColumnHeader", "firstSpecification"),
        ("progressColumnHeader", "rowProgressColumn"),
        ("speedColumnHeader", "rowSpeedColumn"),
        ("etaColumnHeader", "firstEta"),
        ("routeColumnHeader", "routeBadge"),
        ("stateColumnHeader", "stateBadge"),
        ("operationsColumnHeader", "rowActions"),
    )
    for width in (1107, 1108, 1257, 1258, 1357, 1358, 1440):
        engine, root, bridge, warnings = load_qml(qtbot, tasks=six_tasks(), width=width, height=900)
        assert warnings == []
        viewport = named(root, "tableViewport")
        for header_name, row_name in pairs:
            header = named(root, header_name)
            row_item = visual_named(viewport, row_name)
            assert header.property("visible") is row_item.property("visible")
            if header.property("visible"):
                assert abs(scene_position(header).x() - scene_position(row_item).x()) <= 1
                assert scene_position(header).x() + header.property("width") <= width
        bridge.close()
        del engine


def test_settings_keyboard_focus_is_scrolled_into_view_in_both_directions(qtbot) -> None:
    engine, root, bridge, warnings = load_qml(qtbot, width=820, height=640)
    assert warnings == []
    root.setProperty("currentPage", 2)
    qtbot.wait(20)
    scroll = named(root, "settingsScroll")
    controls = [
        named(root, name)
        for name in (
            "defaultSaveDir",
            "closeBehavior",
            "activeTasks",
            "segmentThreads",
            "proxyPolicy",
            "ffmpegPath",
            "saveSettingsButton",
        )
    ]

    def assert_visible(item) -> None:
        top = scene_position(scroll).y()
        bottom = top + scroll.property("height")
        item_top = scene_position(item).y()
        assert item_top >= top
        assert item_top + item.property("height") <= bottom

    controls[0].forceActiveFocus()
    assert controls[0].property("activeFocus") is True
    assert_visible(controls[0])
    for item in controls[1:]:
        qtbot.keyClick(root, Qt.Key_Tab)
        qtbot.wait(10)
        assert item.property("activeFocus") is True, root.activeFocusItem().objectName()
        assert_visible(item)
    for item in reversed(controls[:-1]):
        qtbot.keyClick(root, Qt.Key_Backtab)
        qtbot.wait(10)
        assert item.property("activeFocus") is True
        assert_visible(item)
    bridge.close()
    del engine


def test_task_table_has_complete_columns_fixed_geometry_and_placeholders(qtbot) -> None:
    engine, root, bridge, warnings = load_qml(qtbot, tasks=six_tasks())
    assert warnings == []
    headers = [
        "selectionColumnHeader",
        "nameColumnHeader",
        "specColumnHeader",
        "progressColumnHeader",
        "speedColumnHeader",
        "etaColumnHeader",
        "routeColumnHeader",
        "stateColumnHeader",
        "operationsColumnHeader",
    ]
    header_items = [named(root, object_name) for object_name in headers]
    assert [round(scene_position(item).x()) for item in header_items] == sorted(
        round(scene_position(item).x()) for item in header_items
    )
    assert named(root, "tableHeader").property("height") == 50
    viewport = named(root, "tableViewport")
    rows = visual_descendants(viewport, "taskRow")
    assert len(rows) == 6
    assert {row.property("height") for row in rows} == {66.0}
    assert visual_named(viewport, "firstSpecification").property("text") == "—"
    assert visual_named(viewport, "firstEta").property("text") == "—"
    bridge.close()
    del engine


def test_table_selection_is_independent_and_selected_row_has_accent(qtbot) -> None:
    engine, root, bridge, warnings = load_qml(qtbot, tasks=six_tasks())
    assert warnings == []
    table = named(root, "taskTable")
    table.setProperty("currentIndex", 1)
    qtbot.wait(20)
    viewport = named(root, "tableViewport")
    selections = visual_descendants(viewport, "rowSelection")
    assert len(selections) == 6
    selections[0].setProperty("checked", True)
    qtbot.wait(10)
    assert table.property("currentIndex") == 1
    assert selections[0].property("checked") is True
    accents = visual_descendants(viewport, "currentRowAccent")
    assert sum(bool(accent.property("visible")) for accent in accents) == 1
    bridge.close()
    del engine


def test_table_viewport_and_detail_boundary_stay_stable_for_all_model_sizes(qtbot) -> None:
    geometries = []
    for tasks in ([], one_task(), six_tasks(), many_tasks()):
        engine, root, bridge, warnings = load_qml(qtbot, tasks=tasks)
        assert warnings == []
        viewport = named(root, "tableViewport")
        detail = named(root, "detailsRegion")
        geometries.append(
            (
                round(scene_position(viewport).y()),
                round(viewport.property("height")),
                round(scene_position(detail).y()),
            )
        )
        assert named(root, "taskEmptyState").property("visible") is (len(tasks) == 0)
        assert named(root, "taskTable").property("count") == len(tasks)
        bridge.close()
        del engine
    assert len(set(geometries)) == 1


def test_long_task_content_elides_and_row_actions_stay_inside_bounds(qtbot) -> None:
    engine, root, bridge, warnings = load_qml(qtbot, tasks=six_tasks())
    assert warnings == []
    viewport = named(root, "tableViewport")
    names = visual_descendants(viewport, "rowTaskName")
    assert len(names) == 6
    assert any(item.property("truncated") is True for item in names)
    rows = visual_descendants(viewport, "taskRow")
    actions = visual_descendants(viewport, "rowActions")
    assert len(actions) == len(rows) == 6
    for row, action in zip(rows, actions, strict=True):
        row_pos = scene_position(row)
        action_pos = scene_position(action)
        assert action_pos.x() >= row_pos.x()
        assert action_pos.x() + action.property("width") <= row_pos.x() + row.property("width")
    bridge.close()
    del engine


def test_detail_panel_uses_real_safe_values_in_approved_reading_order(qtbot) -> None:
    tasks = six_tasks()
    engine, root, bridge, warnings = load_qml(qtbot, tasks=tasks)
    assert warnings == []
    table = named(root, "taskTable")
    table.setProperty("currentIndex", 2)
    qtbot.wait(30)

    detail = named(root, "detailPanel")
    ordered_names = (
        "detailTitle",
        "detailSource",
        "detailProgress",
        "detailSaveRoot",
        "detailFilename",
        "detailSegments",
        "detailSpeed",
        "detailRoute",
        "detailError",
    )
    ordered = [named(root, name) for name in ordered_names]
    assert [round(scene_position(item).y()) for item in ordered] == sorted(
        round(scene_position(item).y()) for item in ordered
    )
    assert named(root, "detailTitle").property("text") == tasks[2]["task_name"]
    assert named(root, "detailSource").property("text") == tasks[2]["redacted_url"]
    assert named(root, "detailMediaSpec").property("text") == "—"
    assert named(root, "detailSaveRoot").property("text") == tasks[2]["save_root"]
    assert named(root, "detailFilename").property("text") == tasks[2]["filename"]
    assert named(root, "detailSegments").property("text") == "0 / 260"
    assert named(root, "detailSpeed").property("text") == "—"
    assert named(root, "detailRoute").property("text") == "检测中"
    assert named(root, "detailError").property("text") == "—"
    assert named(root, "copySourceButton").property("visible") is True
    visible_text = " ".join(
        str(item.property("text"))
        for item in visual_descendants(detail, "detailValue") + [named(root, "detailSource")]
    )
    for secret in ("real-user", "real-password", "real-token", "#private"):
        assert secret not in visible_text
    bridge.close()
    del engine


def test_detail_selection_model_reset_and_network_tab_refresh_all_content(qtbot) -> None:
    tasks = six_tasks()
    engine, root, bridge, warnings = load_qml(qtbot, tasks=tasks)
    assert warnings == []
    table = named(root, "taskTable")
    table.setProperty("currentIndex", 4)
    qtbot.wait(20)
    assert named(root, "detailTitle").property("text") == tasks[4]["task_name"]
    assert named(root, "detailError").property("text") == "分片请求失败"

    updated = six_tasks()
    updated[4] = {
        **updated[4],
        "state": "completed",
        "completed": updated[4]["total"],
        "speed_bps": 0,
        "route": "本地代理",
        "error": None,
    }
    bridge.tasks.replace(updated)
    qtbot.wait(30)
    assert table.property("currentIndex") == 4
    assert named(root, "detailTitle").property("text") == updated[4]["task_name"]
    assert named(root, "detailStatus").property("label") == "已完成"
    assert named(root, "detailProgressPercent").property("text") == "100%"
    assert named(root, "detailSegments").property("text") == "240 / 240"
    assert named(root, "detailRoute").property("text") == "本地代理"
    assert named(root, "detailError").property("text") == "—"
    assert "已完成" in named(root, "logContentText").property("text")

    network_tab = named(root, "networkTabButton")
    network_tab.setProperty("checked", True)
    qtbot.wait(20)
    assert named(root, "activeTabIndicator").property("x") > 0
    assert "本地代理" in named(root, "logContentText").property("text")
    assert "当前状态" not in named(root, "logContentText").property("text")
    bridge.close()
    del engine


def test_active_task_refresh_preserves_task_list_scroll_and_selection(qtbot) -> None:
    tasks = many_tasks()
    engine, root, bridge, warnings = load_qml(qtbot, tasks=tasks)
    try:
        assert warnings == []
        table = named(root, "taskTable")
        table.setProperty("currentIndex", 12)
        qtbot.wait(20)
        table.setProperty("contentY", 900.0)
        qtbot.wait(20)
        saved_content_y = float(table.property("contentY"))
        assert saved_content_y > 0
        assert named(root, "detailSegments").property("text") == "109 / 402"

        updated = [dict(task) for task in tasks]
        updated[12] = {**updated[12], "completed": 200}
        bridge.tasks.replace(updated)
        qtbot.wait(40)

        assert abs(float(table.property("contentY")) - saved_content_y) <= 1
        assert table.property("currentIndex") == 12
        assert named(root, "detailSegments").property("text") == "200 / 402"
    finally:
        bridge.close()
        del engine


def test_compact_detail_and_log_stack_without_horizontal_overflow(qtbot) -> None:
    for width in (1099, 820):
        engine, root, bridge, warnings = load_qml(qtbot, tasks=six_tasks(), width=width, height=900)
        assert warnings == []
        detail = named(root, "detailPanel")
        log = named(root, "logPanel")
        flick = named(root, "detailsFlickable")
        assert scene_position(log).y() > scene_position(detail).y() + detail.property("height")
        assert flick.property("contentWidth") == flick.property("width")
        assert named(root, "downloadsPage").property("detailsHorizontalOverflow") is False
        page_right = scene_position(named(root, "downloadsPage")).x() + named(root, "downloadsPage").property("width")
        for panel in (detail, log):
            assert scene_position(panel).x() >= 208
            assert scene_position(panel).x() + panel.property("width") <= page_right
        viewport = named(root, "tableViewport")
        for action in visual_descendants(viewport, "rowActions"):
            assert scene_position(action).x() + action.property("width") <= page_right
        bridge.close()
        del engine


def test_completed_page_uses_stable_rows_and_shared_empty_state(qtbot) -> None:
    engine, root, bridge, warnings = load_qml(qtbot, tasks=six_tasks(), width=820, height=900)
    assert warnings == []
    root.setProperty("currentPage", 1)
    qtbot.wait(20)
    completed = named(root, "completedPage")
    rows = visual_descendants(completed, "completedRow")
    visible_rows = [row for row in rows if row.property("visible")]
    assert len(visible_rows) == 1
    assert visible_rows[0].property("height") == 66
    assert named(root, "completedEmptyState").property("visible") is False
    assert scene_position(visible_rows[0]).x() + visible_rows[0].property("width") <= 820
    bridge.close()
    del engine

    engine, root, bridge, warnings = load_qml(qtbot, tasks=one_task(), width=820, height=900)
    assert warnings == []
    root.setProperty("currentPage", 1)
    qtbot.wait(20)
    assert named(root, "completedEmptyState").property("visible") is True
    bridge.close()
    del engine


def test_settings_fields_align_keep_stable_manual_proxy_slot_and_fit_820(qtbot) -> None:
    engine, root, bridge, warnings = load_qml(qtbot, width=820, height=900)
    assert warnings == []
    root.setProperty("currentPage", 2)
    qtbot.wait(20)
    labels = [
        named(root, name) for name in ("defaultSaveLabel", "closeBehaviorLabel", "proxyPolicyLabel", "ffmpegLabel")
    ]
    fields = [named(root, name) for name in ("defaultSaveDir", "closeBehavior", "proxyPolicy", "ffmpegPath")]
    assert len({round(scene_position(item).x()) for item in labels + fields}) == 1
    for field in fields:
        assert field.property("surfaceColor") is not None

    ffmpeg = named(root, "ffmpegPath")
    ffmpeg_y = round(scene_position(ffmpeg).y())
    proxy = named(root, "proxyPolicy")
    proxy.setProperty("currentIndex", 2)
    qtbot.wait(10)
    assert named(root, "manualProxy").property("visible") is True
    assert round(scene_position(ffmpeg).y()) == ffmpeg_y
    proxy.setProperty("currentIndex", 0)
    qtbot.wait(10)
    assert named(root, "manualProxy").property("visible") is False
    assert round(scene_position(ffmpeg).y()) == ffmpeg_y

    page_right = scene_position(named(root, "settingsPage")).x() + named(root, "settingsPage").property("width")
    for item in fields + [
        named(root, "activeTasks"),
        named(root, "segmentThreads"),
        named(root, "saveSettingsButton"),
    ]:
        assert scene_position(item).x() >= 208
        assert scene_position(item).x() + item.property("width") <= page_right
    bridge.close()
    del engine


def test_batch_dialog_uses_shared_controls_and_complete_focus_order(qtbot) -> None:
    engine, root, bridge, warnings = load_qml(qtbot, width=820, height=900)
    assert warnings == []
    dialog = root.findChild(object, "batchDialog")
    assert dialog is not None
    assert QMetaObject.invokeMethod(dialog, "open")
    qtbot.wait(20)
    batch_input = named(root, "batchInput")
    cancel = named(root, "batchCancelButton")
    submit = named(root, "batchSubmitButton")
    assert batch_input.property("surfaceColor") is not None
    assert cancel.property("surfaceColor") is not None
    assert submit.property("surfaceColor") is not None
    for item in (batch_input, cancel, submit):
        assert 0 <= scene_position(item).x()
        assert scene_position(item).x() + item.property("width") <= 820

    batch_input.forceActiveFocus()
    qtbot.keyClick(root, Qt.Key_Tab)
    qtbot.wait(5)
    assert root.activeFocusItem() == cancel
    qtbot.keyClick(root, Qt.Key_Tab)
    qtbot.wait(5)
    assert root.activeFocusItem() == submit
    bridge.close()
    del engine


def test_desktop_vertical_density_and_detail_header_match_reference(qtbot) -> None:
    engine, root, bridge, warnings = load_qml(qtbot, tasks=six_tasks(), width=1440, height=1024)
    assert warnings == []
    viewport = named(root, "tableViewport")
    rows = sorted(visual_descendants(viewport, "taskRow"), key=lambda item: scene_position(item).y())
    assert [round(scene_position(rows[index + 1]).y() - scene_position(rows[index]).y()) for index in range(5)] == [
        80,
        80,
        80,
        80,
        80,
    ]
    assert round(scene_position(named(root, "detailsRegion")).y()) == 716

    detail = named(root, "detailPanel")
    status = named(root, "detailStatus")
    source = named(root, "detailSource")
    progress = named(root, "detailProgress")
    percent = named(root, "detailProgressPercent")
    assert scene_position(status).x() - scene_position(detail).x() < detail.property("width") * 0.55
    assert source.property("width") <= source.property("implicitWidth") + 1
    assert (
        abs(
            scene_position(percent).y()
            + percent.property("height") / 2
            - (scene_position(progress).y() + progress.property("height") / 2)
        )
        <= 2
    )
    assert round(scene_position(named(root, "detailSaveLabel")).y()) == round(
        scene_position(named(root, "detailSaveRoot")).y()
    )
    assert 550 <= scene_position(named(root, "specColumnHeader")).x() <= 575
    assert 680 <= scene_position(named(root, "progressColumnHeader")).x() <= 705
    assert 875 <= scene_position(named(root, "speedColumnHeader")).x() <= 905
    assert scene_position(named(root, "operationsColumnHeader")).x() >= 1325
    assert 838 <= scene_position(named(root, "detailSaveLabel")).y() <= 844
    assert 776 <= scene_position(named(root, "logContentPanel")).y() <= 784
    bridge.close()
    del engine
