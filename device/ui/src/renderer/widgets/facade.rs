use anyhow::Result;

use super::{WidgetId, WidgetRole};

pub trait LvglFacade {
    fn create_root(&mut self) -> Result<WidgetId>;

    fn create_container(&mut self, parent: WidgetId, role: WidgetRole) -> Result<WidgetId>;

    fn create_label(&mut self, parent: WidgetId, role: WidgetRole) -> Result<WidgetId>;

    fn create_image(&mut self, parent: WidgetId, role: WidgetRole) -> Result<WidgetId>;

    fn create_arc(&mut self, parent: WidgetId, role: WidgetRole) -> Result<WidgetId>;

    /// Create a QR-code widget. Facades without native QR support fall back to a
    /// plain image (the payload set later via `set_text` is simply ignored),
    /// which keeps host/mock renderers working without LVGL.
    fn create_qrcode(&mut self, parent: WidgetId, role: WidgetRole) -> Result<WidgetId> {
        self.create_image(parent, role)
    }

    fn reorder_children(&mut self, parent: WidgetId, order: &[WidgetId]) -> Result<()>;

    fn set_text(&mut self, widget: WidgetId, text: &str) -> Result<()>;

    fn set_selected(&mut self, widget: WidgetId, selected: bool) -> Result<()>;

    fn set_icon(&mut self, widget: WidgetId, icon_key: &str) -> Result<()>;

    fn set_progress(&mut self, widget: WidgetId, value: i32) -> Result<()>;

    fn set_visible(&mut self, widget: WidgetId, visible: bool) -> Result<()>;

    fn set_opacity(&mut self, widget: WidgetId, opacity: u8) -> Result<()> {
        let _ = (widget, opacity);
        Ok(())
    }

    fn set_x_offset(&mut self, widget: WidgetId, offset: i32) -> Result<()> {
        let _ = (widget, offset);
        Ok(())
    }

    fn set_y_offset(&mut self, widget: WidgetId, offset: i32) -> Result<()> {
        let _ = (widget, offset);
        Ok(())
    }

    fn set_scale(&mut self, widget: WidgetId, scale_permille: i32) -> Result<()> {
        let _ = (widget, scale_permille);
        Ok(())
    }

    fn set_geometry(
        &mut self,
        widget: WidgetId,
        x: i32,
        y: i32,
        width: i32,
        height: i32,
    ) -> Result<()> {
        let _ = (widget, x, y, width, height);
        Ok(())
    }

    fn set_variant(
        &mut self,
        widget: WidgetId,
        variant: WidgetRole,
        accent_rgb: u32,
    ) -> Result<()> {
        let _ = (widget, variant, accent_rgb);
        Ok(())
    }

    fn set_accent(&mut self, widget: WidgetId, rgb: u32) -> Result<()> {
        let _ = (widget, rgb);
        Ok(())
    }

    fn destroy(&mut self, widget: WidgetId) -> Result<()>;
}

impl<T> LvglFacade for Box<T>
where
    T: LvglFacade + ?Sized,
{
    fn create_root(&mut self) -> Result<WidgetId> {
        (**self).create_root()
    }

    fn create_container(&mut self, parent: WidgetId, role: WidgetRole) -> Result<WidgetId> {
        (**self).create_container(parent, role)
    }

    fn create_label(&mut self, parent: WidgetId, role: WidgetRole) -> Result<WidgetId> {
        (**self).create_label(parent, role)
    }

    fn create_image(&mut self, parent: WidgetId, role: WidgetRole) -> Result<WidgetId> {
        (**self).create_image(parent, role)
    }

    fn create_arc(&mut self, parent: WidgetId, role: WidgetRole) -> Result<WidgetId> {
        (**self).create_arc(parent, role)
    }

    fn create_qrcode(&mut self, parent: WidgetId, role: WidgetRole) -> Result<WidgetId> {
        (**self).create_qrcode(parent, role)
    }

    fn reorder_children(&mut self, parent: WidgetId, order: &[WidgetId]) -> Result<()> {
        (**self).reorder_children(parent, order)
    }

    fn set_text(&mut self, widget: WidgetId, text: &str) -> Result<()> {
        (**self).set_text(widget, text)
    }

    fn set_selected(&mut self, widget: WidgetId, selected: bool) -> Result<()> {
        (**self).set_selected(widget, selected)
    }

    fn set_icon(&mut self, widget: WidgetId, icon_key: &str) -> Result<()> {
        (**self).set_icon(widget, icon_key)
    }

    fn set_progress(&mut self, widget: WidgetId, value: i32) -> Result<()> {
        (**self).set_progress(widget, value)
    }

    fn set_visible(&mut self, widget: WidgetId, visible: bool) -> Result<()> {
        (**self).set_visible(widget, visible)
    }

    fn set_opacity(&mut self, widget: WidgetId, opacity: u8) -> Result<()> {
        (**self).set_opacity(widget, opacity)
    }

    fn set_x_offset(&mut self, widget: WidgetId, offset: i32) -> Result<()> {
        (**self).set_x_offset(widget, offset)
    }

    fn set_y_offset(&mut self, widget: WidgetId, offset: i32) -> Result<()> {
        (**self).set_y_offset(widget, offset)
    }

    fn set_scale(&mut self, widget: WidgetId, scale_permille: i32) -> Result<()> {
        (**self).set_scale(widget, scale_permille)
    }

    fn set_geometry(
        &mut self,
        widget: WidgetId,
        x: i32,
        y: i32,
        width: i32,
        height: i32,
    ) -> Result<()> {
        (**self).set_geometry(widget, x, y, width, height)
    }

    fn set_variant(
        &mut self,
        widget: WidgetId,
        variant: WidgetRole,
        accent_rgb: u32,
    ) -> Result<()> {
        (**self).set_variant(widget, variant, accent_rgb)
    }

    fn set_accent(&mut self, widget: WidgetId, rgb: u32) -> Result<()> {
        (**self).set_accent(widget, rgb)
    }

    fn destroy(&mut self, widget: WidgetId) -> Result<()> {
        (**self).destroy(widget)
    }
}
