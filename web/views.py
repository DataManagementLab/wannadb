from django.utils.safestring import mark_safe
from django.views.generic import TemplateView, DetailView, ListView

from web.models import Document, Collection


class IndexView(ListView):
    template_name = 'index.html'
    model = Collection
    context_object_name = 'collections'


class CollectionView(DetailView):
    model = Collection
    template_name = 'collection.html'
    context_object_name = 'collection'


class DocumentView(DetailView):
    template_name = 'document.html'
    model = Document
    context_object_name = 'doc'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Mark nuggets in text
        old_start = -1
        old_end = -1
        custom_start = -1
        custom_end = -1

        nuggets_in_order = list(context["doc"].nugget_set.all().order_by("start")) # list(sorted(self.document.nuggets, key=lambda x: x.start_char))

        nuggets_to_confirmed_nuggets = {bv.nugget: bv for bv in context["doc"].box}

        idx_mapper = {}
        base_formatted_text = ""

        next_unseen_nugget_idx = 0
        inside = False
        current_inside_nuggets = []

        # For every char in the original document
        for idx, char in enumerate(list(context["doc"].text)):
            if char == "\n":
                char = "<br>"
            # Get all nuggets starting here (unseen and start char is not greater than current index)
            # and store them to make sure they are closed afterwards
            while next_unseen_nugget_idx < len(nuggets_in_order):
                if nuggets_in_order[next_unseen_nugget_idx].start > idx:
                    break
                current_inside_nuggets.append(nuggets_in_order[next_unseen_nugget_idx])
                next_unseen_nugget_idx += 1

            # Are we outside?
            if len(current_inside_nuggets) == 0:
                # Just write out the char and map index to len - 1
                base_formatted_text += char
                idx_mapper[idx] = len(base_formatted_text) - 1
            # Are we inside?
            else:
                # Determine if there are any nuggets ending here and remove them from the list of active nuggets
                for i in range(len(current_inside_nuggets) - 1, -1, -1):
                    n = current_inside_nuggets[i]
                    if n.end == idx:
                        del current_inside_nuggets[i]

                # Did we switch from outside to inside?
                if not inside:
                    inside = True
                    n = current_inside_nuggets[0]
                    base_formatted_text += f"<span class='nugget' style='background-color: {n.label.color}'><b>"
                    if n in nuggets_to_confirmed_nuggets:
                        base_formatted_text += f"<span class='nugget-label' style='background-color: {n.label.color}'>{nuggets_to_confirmed_nuggets[n].box_attribute.name}:</span> "
                    base_formatted_text += char
                    idx_mapper[idx] = len(base_formatted_text) - 1
                # Inside
                else:
                    # But now the questions: really inside or at the end?
                    if len(current_inside_nuggets) == 0:
                        base_formatted_text += "</span></b>"
                        inside = False
                    base_formatted_text += char
                    idx_mapper[idx] = len(base_formatted_text) - 1


        context["text"] = mark_safe(base_formatted_text)

        return context

