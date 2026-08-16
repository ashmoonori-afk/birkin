#include <gtk/gtk.h>
#include <stdio.h>
#include <unistd.h>

static int counter = 0;
static GtkWidget *counter_label;

static void increment_counter(GtkWidget *widget, gpointer data) {
    (void)data;
    counter += 1;
    char text[64];
    snprintf(text, sizeof(text), "count=%d", counter);
    gtk_label_set_text(GTK_LABEL(counter_label), text);
    snprintf(text, sizeof(text), "Increment synthetic counter (%d)", counter);
    gtk_button_set_label(GTK_BUTTON(widget), text);
}

static gboolean report_ready(GtkWidget *widget, GdkEvent *event, gpointer data) {
    (void)widget;
    (void)event;
    (void)data;
    printf("READY %d\n", getpid());
    fflush(stdout);
    return FALSE;
}

int main(int argc, char **argv) {
    gtk_init(&argc, &argv);

    GtkWidget *window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_title(
        GTK_WINDOW(window),
        "Birkin Computer Use QA Fixture"
    );
    gtk_window_set_default_size(GTK_WINDOW(window), 560, 420);
    gtk_window_move(GTK_WINDOW(window), 160, 160);
    g_signal_connect(window, "destroy", G_CALLBACK(gtk_main_quit), NULL);
    g_signal_connect(window, "map-event", G_CALLBACK(report_ready), NULL);

    GtkWidget *box = gtk_box_new(GTK_ORIENTATION_VERTICAL, 14);
    gtk_container_set_border_width(GTK_CONTAINER(box), 24);
    gtk_container_add(GTK_CONTAINER(window), box);

    GtkWidget *heading = gtk_label_new("Birkin Computer Use QA");
    gtk_widget_set_name(heading, "fixture-heading");
    gtk_box_pack_start(GTK_BOX(box), heading, FALSE, FALSE, 0);

    GtkWidget *entry = gtk_entry_new();
    gtk_entry_set_text(GTK_ENTRY(entry), "before");
    gtk_entry_set_placeholder_text(GTK_ENTRY(entry), "Synthetic value");
    gtk_widget_set_name(entry, "fixture-value");
    gtk_box_pack_start(GTK_BOX(box), entry, FALSE, FALSE, 0);

    GtkWidget *button = gtk_button_new_with_label(
        "Increment synthetic counter"
    );
    gtk_widget_set_name(button, "fixture-increment");
    g_signal_connect(
        button,
        "clicked",
        G_CALLBACK(increment_counter),
        NULL
    );
    gtk_box_pack_start(GTK_BOX(box), button, FALSE, FALSE, 0);

    counter_label = gtk_label_new("count=0");
    gtk_widget_set_name(counter_label, "fixture-counter");
    gtk_box_pack_start(GTK_BOX(box), counter_label, FALSE, FALSE, 0);

    GtkWidget *scroll = gtk_scrolled_window_new(NULL, NULL);
    gtk_widget_set_size_request(scroll, 480, 180);
    GtkWidget *list = gtk_list_box_new();
    for (int row = 1; row <= 30; row++) {
        char text[48];
        snprintf(text, sizeof(text), "Synthetic row %d", row);
        gtk_list_box_insert(GTK_LIST_BOX(list), gtk_label_new(text), -1);
    }
    gtk_container_add(GTK_CONTAINER(scroll), list);
    gtk_box_pack_start(GTK_BOX(box), scroll, TRUE, TRUE, 0);

    gtk_widget_show_all(window);
    gtk_main();
    return 0;
}
